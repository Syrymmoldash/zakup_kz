import os
import zipfile

from selenium import webdriver


def split_proxy(proxy):
    head, tail = proxy.replace('http://', '').replace('http://', '').split(sep='@')
    login, pw = head.split(sep=':')
    ip, port = tail.split(sep=':')
    return ip, port, login, pw


def gen_manifest(PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS):
    manifest_json = """
    {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Chrome Proxy",
        "permissions": [
            "proxy",
            "tabs",
            "unlimitedStorage",
            "storage",
            "<all_urls>",
            "webRequest",
            "webRequestBlocking"
        ],
        "background": {
            "scripts": ["background.js"]
        },
        "minimum_chrome_version":"22.0.0"
    }
    """

    background_js = """
    var config = {
            mode: "fixed_servers",
            rules: {
            singleProxy: {
                scheme: "http",
                host: "%s",
                port: parseInt(%s)
            },
            bypassList: ["localhost"]
            }
        };

    chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});

    function callbackFn(details) {
        return {
            authCredentials: {
                username: "%s",
                password: "%s"
            }
        };
    }

    chrome.webRequest.onAuthRequired.addListener(
                callbackFn,
                {urls: ["<all_urls>"]},
                ['blocking']
    );
    """ % (PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS)

    return manifest_json, background_js
    

def get_chromedriver(path, proxy, user_agent=None):
    use_proxy = True if proxy else False

    if use_proxy:
        PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS = split_proxy(proxy)
        manifest_json, background_js = gen_manifest(PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS)
    
    chrome_options = webdriver.ChromeOptions()
    if use_proxy:
        pluginfile = 'proxy_auth_plugin.zip'

        with zipfile.ZipFile(pluginfile, 'w') as zp:
            zp.writestr("manifest.json", manifest_json)
            zp.writestr("background.js", background_js)
        chrome_options.add_extension(pluginfile)
    if user_agent:
        chrome_options.add_argument('--user-agent=%s' % user_agent)
        
    driver = webdriver.Chrome(
        path,
        options=chrome_options)
    return driver

def main(proxy):
    driver = get_chromedriver(proxy, use_proxy=True)
    #driver.get('https://www.google.com/search?q=my+ip+address')
    driver.get('https://httpbin.org/ip')
    return driver


if __name__ == '__main__':
    proxy = 'http://yibnnqpy:1ls3qxgss949@45.87.249.134:7712'
    d = main(proxy)