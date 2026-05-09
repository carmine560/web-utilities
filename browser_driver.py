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
    implicitly_wait=2,
):
    """Initialize a Selenium WebDriver with specified options."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    if user_data_directory and profile_directory:
        options.add_argument("--user-data-dir=" + user_data_directory)
        options.add_argument("--profile-directory=" + profile_directory)
    options.add_argument("--window-size=1600,1000")
    # Suppress the session restore dialog to prevent it from blocking
    # navigation.
    options.add_argument("--restore-last-session=false")

    driver = webdriver.Chrome(options=options)
    if not headless:
        try:
            driver.maximize_window()
        except Exception:
            pass
    driver.implicitly_wait(implicitly_wait)
    driver._trading_peripheral_wait_timeout = max(float(implicitly_wait), 1.0)

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


def _handle_navigation_command(driver, instruction, element=None, text=None):
    """Handle page navigation commands."""
    command, argument, _ = _unpack_instruction(instruction)

    if command == "get":
        driver.get(argument)
    elif command == "refresh":
        driver.refresh()

    return True


def _handle_element_command(driver, instruction, element=None, text=None):
    """Handle element interaction commands."""
    command, argument, additional_argument = _unpack_instruction(instruction)

    if command == "clear":
        _wait_for_visible(driver, argument).clear()
    elif command == "click":
        target = _wait_for_clickable(driver, argument)
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", target
        )
        target.click()
    elif command == "send_keys":
        target = _wait_for_visible(driver, argument)
        if additional_argument == "enter":
            target.send_keys(Keys.ENTER)
        elif additional_argument == "element":
            target.send_keys(element)
        else:
            target.send_keys(additional_argument)

    return True


def _handle_text_command(driver, instruction, element=None, text=None):
    """Handle text extraction command."""
    _, argument, _ = _unpack_instruction(instruction)
    text.append(_wait_for_visible(driver, argument).text)
    return True


def _handle_wait_command(driver, instruction, element=None, text=None):
    """Handle blocking command."""
    _, argument, _ = _unpack_instruction(instruction)
    time.sleep(float(argument))
    return True


def _handle_control_flow_command(driver, instruction, element=None, text=None):
    """Handle conditional control-flow commands."""
    command, argument, additional_argument = _unpack_instruction(instruction)

    if command == "exist":
        if driver.find_elements(By.XPATH, argument):
            execute_action(
                driver, additional_argument, element=element, text=text
            )
        elif text is not None:
            match = re.search(
                r'//.*\[contains\(text\(\), "(.+)"\)\]', argument
            )
            if match:
                text.append(f"{match.group(1)} does not exist.")
    elif command == "for":
        for item in argument.split(", "):
            execute_action(
                driver, additional_argument, element=item, text=text
            )
            time.sleep(1)

    return True


def _get_wait_timeout(driver):
    """Return the explicit wait timeout configured for the driver."""
    return getattr(driver, "_trading_peripheral_wait_timeout", 5.0)


def _wait_for_visible(driver, xpath):
    """Wait until an element is visible and return it."""
    return WebDriverWait(driver, _get_wait_timeout(driver)).until(
        EC.visibility_of_element_located((By.XPATH, xpath))
    )


def _find_interactable_match(driver, xpath):
    """Return the first displayed, enabled match for an XPath."""
    for candidate in driver.find_elements(By.XPATH, xpath):
        if candidate.is_displayed() and candidate.is_enabled():
            return candidate
    return None


def _wait_for_clickable(driver, xpath):
    """Wait until any matching element is clickable and return it."""
    try:
        return WebDriverWait(driver, _get_wait_timeout(driver)).until(
            lambda current_driver: _find_interactable_match(
                current_driver, xpath
            )
        )
    except TimeoutException as exc:
        matches = len(driver.find_elements(By.XPATH, xpath))
        message = (
            "No interactable match for XPath "
            f"{xpath!r}; matches={matches}; "
            f"url={getattr(driver, 'current_url', '')!r}; "
            f"title={getattr(driver, 'title', '')!r}"
        )
        raise TimeoutException(message) from exc


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
    # Conditional control-flow commands
    "exist": _handle_control_flow_command,
    "for": _handle_control_flow_command,
}


def execute_action(driver, action, element=None, text=None):
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
            if not handler(driver, instruction, element=element, text=text):
                return False
        except BrowserAutomationError:
            raise
        except Exception as exc:
            raise BrowserAutomationError(
                f"Browser instruction failed: {instruction!r}"
            ) from exc

    return True
