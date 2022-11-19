from flask import Flask, json
from selenium import webdriver
# from seleniumwire import webdriver
import os
import platform
import argparse
import json
import time

# auto login related imports
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from chrome_proxy import get_chromedriver


if platform.system() == 'Windows':
    user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.0 Safari/537.36'
else:
    user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.88 Safari/537.36'
    # user_agent = 'Mozilla/5.0 (Windows NT 6.3; rv:36.0) Gecko/20100101 Firefox/36.0'


def init_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str)

    parser.add_argument('--auto_login', type=int, default=0)
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--proxy_monitor', type=str, default="")
    parser.add_argument('--proxy_apply', type=str, default="")

    return parser.parse_args()


def run_chrome(proxy=None, auto_login=False, config_path="", mode=''):

    if not auto_login:
        path = os.path.join(os.getcwd(), 'chromedriver')
        path = path if os.path.exists(path) else 'chromedriver'
        driver = get_chromedriver(path, proxy, user_agent=user_agent)

        driver.get('https://v3bl.goszakup.gov.kz/ru/user/')
        return driver
    elif auto_login == 1:
        # auto login code from Syrym
        from pyPythonRPA.Robot import pythonRPA
        config = json.load(open(config_path))

        ecp_path = config['cert_path']
        ecp_password = config['cert_password']
        portal_password = config['portal_password']
        options = Options()
        options.binary_location = r"C:\Users\Administrator\Desktop\GosZakup\Resources\chrome\chrome.exe"
        driver = webdriver.Chrome(executable_path=r"C:\Users\Administrator\Desktop\GosZakup\Resources\chromedriver\chromedriver.exe", options=options)
        driver.maximize_window()
        driver.get('https://v3bl.goszakup.gov.kz/ru/user/')
        driver.find_element(By.NAME, "selectP12File").click()
        pythonRPA.bySelector([{"title":"Select certificate","class_name":"SunAwtDialog","backend":"uia"}]).wait_appear(30)
        pythonRPA.bySelector([{"title":"Select certificate","class_name":"SunAwtDialog","backend":"uia"}]).right_click()
        pythonRPA.keyboard.press("down", 1, timing_before=0.5, timing_after=0.5)
        pythonRPA.keyboard.press("enter", 1, 0.5)
        pythonRPA.bySelector([{"title":"Select certificate","class_name":"SunAwtDialog","backend":"uia"},{"ctrl_index":0}]).right_click()
        pythonRPA.keyboard.press("down", 1, timing_before=0.5, timing_after=0.5)
        pythonRPA.keyboard.press("enter", 1, 0.5)
        pythonRPA.keyboard.press("down", 3)
        pythonRPA.keyboard.press("enter", 1, 0.5)
        pythonRPA.bySelector([{"title":"Select certificate","class_name":"SunAwtDialog","backend":"uia"},{"ctrl_index":0}]).right_click()
        pythonRPA.keyboard.press("down", 1, timing_before=0.5, timing_after=0.5)
        pythonRPA.keyboard.press("enter", 1, 0.5)
        pythonRPA.keyboard.press("up", 3)
        pythonRPA.keyboard.press("enter", 1, 0.5)
        pythonRPA.mouse.click()
        pythonRPA.bySelector([{"title": "Открыть файл", "class_name": "SunAwtDialog", "backend": "uia"}]).wait_appear(30)
        pythonRPA.keyboard.write(ecp_path)
        pythonRPA.keyboard.press("enter")
        pythonRPA.bySelector([{"title":"Enter password","class_name":"SunAwtDialog","backend":"uia"}]).wait_appear(30)
        pythonRPA.keyboard.write(ecp_password)
        pythonRPA.keyboard.press("enter")
        WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.NAME, "password")))
        driver.find_element(By.NAME, "password").send_keys(portal_password)
        driver.find_element(By.ID, "agreed_check").click()
        WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Войти')]")))
        driver.find_element(By.XPATH, "//*[contains(text(), 'Войти')]").click()
        WebDriverWait(driver, 30).until(EC.visibility_of_element_located((By.ID, "main-nav")))
        return driver

    elif auto_login == 2:

        # auto login code from Boris

        import rpa as r
        r.init(visual_automation=True, chrome_browser = False)

        config = json.load(open(config_path))

        ua = None

        if mode == 'monitor':
            cert_path = config['cert_path_monitor']
            cert_password = config['cert_password_monitor']
            portal_password = config['portal_password_monitor']
            ua = user_agent
        elif mode == 'apply':
            cert_path = config['cert_path']
            cert_password = config['cert_password']
            portal_password = config['portal_password']
            ua = 'Mozilla/5.0 (Windows NT 6.3; rv:36.0) Gecko/20100101 Firefox/36.0'
        else:
            raise Exception('no mode specified, leaving')

        path = os.path.join(os.getcwd(), 'chromedriver')
        path = path if os.path.exists(path) else 'chromedriver'
        # driver = get_chromedriver(path, proxy, user_agent=user_agent)
        driver = get_chromedriver(path, proxy, user_agent=ua)

        driver.get('https://v3bl.goszakup.gov.kz/ru/user/')
        WebDriverWait(driver, 30).until(EC.visibility_of_element_located((By.NAME, "selectP12File")))
        driver.find_element(by=By.XPATH, value='//input[@name="selectP12File"]').click()
        r.dclick('choose_sert.png')
        r.keyboard(cert_path)
        r.click('open.png')
        r.keyboard(cert_password)
        r.click('ok.png')

        WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.NAME, "password")))
        driver.find_element(by=By.XPATH, value='//input[@type="password"]')
        driver.find_element(By.NAME, "password").send_keys(portal_password)
        driver.find_element(By.ID, "agreed_check").click()
        WebDriverWait(driver, 30).until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Войти')]")))

        driver.find_element(By.XPATH, "//*[contains(text(), 'Войти')]").click()
        WebDriverWait(driver, 30).until(EC.visibility_of_element_located((By.ID, "main-nav")))
        return driver


def get_cookie(driver):
    for record in driver.get_cookies():
        if record['name'] == 'ci_session':
            return record['value']

api = Flask(__name__)

@api.route('/token', methods=['GET'])
def token():
    global driver
    driver.refresh()
    while ('Выберите ключ' in driver.page_source) or ('/login' in driver.current_url):
        print("PLEASE RELOGIN!")
        if args.auto_login:
            driver.quit()
            # del driver
            driver = run_chrome(args.proxy_monitor, args.auto_login, args.config, mode='monitor')
        time.sleep(5)

    return get_cookie(driver)


@api.route('/token2', methods=['GET'])
def token2():
    global driver2
    driver2.refresh()
    while ('Выберите ключ' in driver2.page_source) or ('/login' in driver2.current_url):
        print("PLEASE RELOGIN!")
        if args.auto_login:
            driver.quit()
            # del driver2
            driver2 = run_chrome(args.proxy_monitor, args.auto_login, args.config, mode='apply')
        time.sleep(5)

    return get_cookie(driver2)


if __name__ == '__main__':
    args = init_args()

    driver = run_chrome(args.proxy_monitor, args.auto_login, args.config, mode='monitor')
    driver2 = run_chrome(args.proxy_apply, args.auto_login, args.config, mode='apply')
    api.run(port=args.port)
