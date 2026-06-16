"""Selenium WebDriver action execution utilities."""

import re
import time

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from core_utilities.config_validation import evaluate_value
from core_utilities.errors import BrowserAutomationError

# Browser Driver Initialization


def initialize(
    headless=True,
    user_data_directory=None,
    profile_directory=None,
):
    """Initialize a Selenium WebDriver with specified options."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    if user_data_directory and profile_directory:
        options.add_argument("--user-data-dir=" + user_data_directory)
        options.add_argument("--profile-directory=" + profile_directory)

    driver = webdriver.Chrome(options=options)

    if headless:
        driver.execute_cdp_cmd(
            "Network.setUserAgentOverride",
            {
                "userAgent": driver.execute_script(
                    "return navigator.userAgent"
                ).replace("Headless", "")
            },
        )

    return driver


# Action Execution Pipeline


def _unpack_instruction(instruction):
    """Extract command name and up to two arguments from an instruction."""
    return (
        instruction[0],
        instruction[1] if len(instruction) > 1 else None,
        instruction[2] if len(instruction) > 2 else None,
    )


def _handle_navigation_command(
    driver, instruction, _element, _text, _wait_timeout
):
    """Handle page navigation commands."""
    command, argument, _ = _unpack_instruction(instruction)

    if command == "get":
        driver.get(argument)
    elif command == "refresh":
        driver.refresh()

    return True


def _handle_element_command(driver, instruction, element, _text, wait_timeout):
    """Handle element interaction commands."""
    command, argument, additional_argument = _unpack_instruction(instruction)

    if command == "clear":
        _wait_for_visible(driver, argument, wait_timeout).clear()
    elif command == "click":
        target = _wait_for_clickable(driver, argument, wait_timeout)
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", target
        )
        target.click()
    elif command == "send_keys":
        target = _wait_for_visible(driver, argument, wait_timeout)
        if additional_argument == "enter":
            target.send_keys(Keys.ENTER)
        elif additional_argument == "element":
            target.send_keys(element)
        else:
            target.send_keys(additional_argument)

    return True


def _handle_text_command(driver, instruction, _element, text, wait_timeout):
    """Handle text extraction command."""
    _, argument, _ = _unpack_instruction(instruction)
    text.append(_wait_for_visible(driver, argument, wait_timeout).text)
    return True


def _handle_wait_command(driver, instruction, _element, _text, wait_timeout):
    """Handle blocking and wait commands."""
    command, argument, additional_argument = _unpack_instruction(instruction)

    if command == "sleep":
        time.sleep(float(argument))
    elif command == "wait_absent":
        timeout = float(additional_argument or wait_timeout)
        WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element_located((By.XPATH, argument))
        )

    return True


def _handle_control_flow_command(
    driver, instruction, element, text, wait_timeout
):
    """Handle conditional control-flow commands."""
    command, argument, additional_argument = _unpack_instruction(instruction)

    if command == "exist":
        if driver.find_elements(By.XPATH, argument):
            execute_action(
                driver,
                additional_argument,
                element=element,
                text=text,
                wait_timeout=wait_timeout,
            )
        elif text is not None:
            matched = re.search(
                r'//.*\[contains\(text\(\), "(.+)"\)\]', argument
            )
            if matched:
                text.append(f"{matched.group(1)} does not exist.")
    elif command == "for":
        for item in argument.split(", "):
            execute_action(
                driver,
                additional_argument,
                element=item,
                text=text,
                wait_timeout=wait_timeout,
            )
            time.sleep(1)

    return True


def _wait_for_visible(driver, xpath, wait_timeout):
    """Wait until an element is visible and return it."""
    return WebDriverWait(driver, wait_timeout).until(
        EC.visibility_of_element_located((By.XPATH, xpath))
    )


def _find_interactable_match(driver, xpath):
    """Return the first displayed, enabled match for an XPath."""
    for candidate in driver.find_elements(By.XPATH, xpath):
        if candidate.is_displayed() and candidate.is_enabled():
            return candidate
    return None


def _wait_for_clickable(driver, xpath, wait_timeout):
    """Wait until any matching element is clickable and return it."""
    try:
        return WebDriverWait(driver, wait_timeout).until(
            lambda current_driver: _find_interactable_match(
                current_driver, xpath
            )
        )
    except TimeoutException as e:
        matches = len(driver.find_elements(By.XPATH, xpath))
        message = (
            "No interactable match for XPath "
            f"{xpath!r}; matches={matches}; "
            f"url={getattr(driver, 'current_url', '')!r}; "
            f"title={getattr(driver, 'title', '')!r}"
        )
        raise TimeoutException(message) from e


_COMMAND_DISPATCH = {
    # Navigation commands
    "get": _handle_navigation_command,
    "refresh": _handle_navigation_command,
    # Element interaction commands
    "clear": _handle_element_command,
    "click": _handle_element_command,
    "send_keys": _handle_element_command,
    # Text extraction command
    "text": _handle_text_command,
    # Blocking command
    "sleep": _handle_wait_command,
    "wait_absent": _handle_wait_command,
    # Conditional control-flow commands
    "exist": _handle_control_flow_command,
    "for": _handle_control_flow_command,
}


def execute_action(driver, action, element=None, text=None, wait_timeout=5.0):
    """Execute a series of actions on a Selenium WebDriver."""
    if isinstance(action, str):
        action = evaluate_value(action)

    for instruction in action:
        command = instruction[0]
        handler = _COMMAND_DISPATCH.get(command)

        if not handler:
            raise BrowserAutomationError(
                f"Unrecognized browser command: {command!r}"
            )
        try:
            if not handler(
                driver,
                instruction,
                element,
                text,
                wait_timeout,
            ):
                return False
        except BrowserAutomationError:
            raise
        except Exception as e:
            raise BrowserAutomationError(
                f"Browser instruction failed: {instruction!r}"
            ) from e

    return True
