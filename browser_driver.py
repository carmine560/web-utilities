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


def execute_action(driver, action, element=None, text=None):
    """Execute a series of actions on a Selenium WebDriver."""
    if isinstance(action, str):
        action = configuration.evaluate_value(action)

    for instruction in action:
        command = instruction[0]
        argument = instruction[1] if len(instruction) > 1 else None
        additional_argument = instruction[2] if len(instruction) > 2 else None

        if command == "clear":
            driver.find_element(By.XPATH, argument).clear()
        elif command == "click":
            driver.find_element(By.XPATH, argument).click()
        elif command == "get":
            driver.get(argument)
        elif command == "refresh":
            driver.refresh()
        elif command == "send_keys":
            if additional_argument == "enter":
                driver.find_element(By.XPATH, argument).send_keys(Keys.ENTER)
            elif additional_argument == "element":
                driver.find_element(By.XPATH, argument).send_keys(element)
            else:
                driver.find_element(By.XPATH, argument).send_keys(
                    additional_argument
                )
        elif command == "sleep":
            time.sleep(float(argument))
        elif command == "text":
            text.append(driver.find_element(By.XPATH, argument).text)

        # Control Flow Commands
        elif command == "exist":
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

        else:
            print(f"'{command}' is not a recognized command.")
            return False
    return True
