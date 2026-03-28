"""Manage and execute actions with a Selenium WebDriver."""

import os
import re
import shutil
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

from core_utilities import configuration


# Browser Driver Initialization


def initialize(
    headless=True,
    user_data_directory=None,
    profile_directory=None,
    implicitly_wait=2,
):
    """Initialize a Selenium WebDriver with specified options."""
    executable_path = ChromeDriverManager().install()
    service = Service(executable_path=executable_path)
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    if user_data_directory and profile_directory:
        # Remove a stale lock file to ensure Chrome can acquire the profile
        # cleanly.
        lock_file = os.path.join(
            user_data_directory, profile_directory, "LOCK"
        )
        if os.path.exists(lock_file):
            os.remove(lock_file)
        options.add_argument("--user-data-dir=" + user_data_directory)
        options.add_argument("--profile-directory=" + profile_directory)

    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(implicitly_wait)

    driver.execute_cdp_cmd(
        "Network.setUserAgentOverride",
        {
            "userAgent": driver.execute_script(
                "return navigator.userAgent"
            ).replace("Headless", "")
        },
    )

    os_type_directory = os.path.dirname(
        os.path.dirname(os.path.dirname(executable_path))
    )
    version_directories = [
        os.path.join(os_type_directory, subdirectory)
        for subdirectory in os.listdir(os_type_directory)
        if (
            os.path.isdir(os.path.join(os_type_directory, subdirectory))
            and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", subdirectory)
        )
    ]
    version_directories.sort(key=os.path.getctime, reverse=True)
    for version_directory in version_directories[1:]:
        shutil.rmtree(version_directory)

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
        driver.find_element(By.XPATH, argument).clear()
    elif command == "click":
        driver.find_element(By.XPATH, argument).click()
    elif command == "send_keys":
        target = driver.find_element(By.XPATH, argument)
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
    text.append(driver.find_element(By.XPATH, argument).text)
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
        action = configuration.evaluate_value(action)

    for instruction in action:
        command = instruction[0]
        handler = _COMMAND_DISPATCH.get(command)

        if not handler:
            print(f"'{command}' is not a recognized command.")
            return False
        if not handler(driver, instruction, element=element, text=text):
            return False

    return True
