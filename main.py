import requests
import dotenv
import os
import time
from selenium.common import exceptions as sException
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By 
from selenium.webdriver.support.ui import WebDriverWait 
from selenium.webdriver.support import expected_conditions as EC 
from selenium.webdriver.common.keys import Keys
import pyperclip
import threading
import random
import csv
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
import logzero
from logzero import logger, LogFormatter
import logging

API_URL = 'http://local.adspower.net:50325/'

# Construct the absolute path to the config files
current_dir = os.path.dirname(os.path.abspath(__file__))    
dotenv_path = os.path.join(current_dir, '.env')
profiles_csv_path = os.path.join(current_dir, 'profiles.csv')
logs_dir = os.path.join(current_dir, 'logs')
extension_path = os.path.join(current_dir, 'captcha-solver-extension')
reports_dir = os.path.join(current_dir, 'reports')

CONFIG = dotenv.dotenv_values(dotenv_path=dotenv_path)

def setup_logger(log_file):
    """Set up a logger for a specific run."""
    formatter = LogFormatter()
    
    # Create a new logger object
    custom_logger = logzero.setup_logger(name=log_file, logfile=log_file, level=logging.DEBUG, formatter=formatter)
    
    return custom_logger

def get_profiles()->list:
    profiles = []
    use_input_profiles = []
    try:            
        with open(profiles_csv_path, mode='r') as file:
            csv_reader = csv.reader(file)
            
            # Loop through each row in the CSV
            for row in csv_reader:
                if len(row) > 0:  # Ensure the row is not empty
                    try:
                        id = row[0]  # Access first column
                        use_input_profiles.append(id)
                    except IndexError:
                        pass
    except:
        logger.exception('Error reading profiles.csv')
    
    try:
        if len(use_input_profiles) > 0:
            all_available_profiles = []
            page = 0
            while True:
                time.sleep(1)
                page += 1        
                resp = requests.get(f'{API_URL}api/v1/user/list?page_size=50&page={page}').json()
                if resp['code'] != 0:
                    logger.error(f'Error fetching profiles from api {resp["msg"]}')
                    return profiles
                elif len(resp['data']['list']) == 0:
                    break
                else:
                    for i in resp['data']['list']:
                        all_available_profiles.append({
                            'integer_id':i['serial_number'],
                            'alphanumeric_id':i['user_id']
                        })

            for i in use_input_profiles:
                for j in all_available_profiles:
                    if i == j['integer_id']:
                        profiles.append(j)
            return profiles       
        else:
            return profiles
    except:
        logger.get('Error fetching profiles from api')
        return profiles
    
def open_browser_profile(user_id:str, logger:logging.Logger):
    try:
        while(True):
            try:
                response = requests.get(f'{API_URL}api/v1/browser/start?user_id={user_id}').json()
            except requests.exceptions.ConnectionError:
                logger.error('AdsPower connection error')
                return

            if response['code'] != 0:
                if 'too many request' in response['msg'].lower():
                    wait_time = random.randint(1, 5)
                    logger.debug(f'Waiting for {wait_time} seconds to avoid too many api requests')
                    time.sleep(wait_time)
                    continue
                logger.error('API error when launching profile')
                logger.debug(response['msg'])
                return
            else:
                break

        chrome_driver = response["data"]["webdriver"]
        service = Service(executable_path=chrome_driver)
        chrome_options = Options()

        chrome_options.add_experimental_option("debuggerAddress", response["data"]["ws"]["selenium"])
        logging_prefs = {'performance': 'ALL'}
        chrome_options.set_capability('goog:loggingPrefs', logging_prefs)
        # chrome_options.add_argument(f'--load-extension={extension_path}')

        try:
            driver = webdriver.Chrome(service=service, options=chrome_options)
            return driver    
        except:
            logger.exception('Exception when connecting to browser')
            return
    except:
        logger.exception('Exception when opening browser')
        return

def close_browser_profile(user_id:str, driver:webdriver.Chrome, logger:logging.Logger):
    driver.quit()
    requests.get(f'{API_URL}api/v1/browser/stop?user_id={user_id}')

def wallet_login(driver:webdriver.Chrome, logger:logging.Logger):
    # Open OKX wallet login page
    driver.get('chrome-extension://mcohilncbfahbmgdjkbpemcciiolgcge/popup.html')
    
    for _ in range(5): # retry stale element
        time.sleep(1)
        try:
            password_field = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[type="password"]'))
            )
            password_field.click() # shifting focus to input field
            time.sleep(0.5)
            password_field.send_keys(CONFIG['WALLET_PASSWORD']) # type password
            time.sleep(0.5)
            password_field.send_keys(Keys.RETURN) # press Enter key
            driver.refresh()

            driver.execute_script("window.open('https://pioneer.particle.network/en/point', '_blank');")
            time.sleep(5)
            handles = driver.window_handles
            break
        except sException.TimeoutException:
            logger.debug('Timeout clicking password field')
            try:
                create_wallet = driver.find_element(By.XPATH, f"//span[text()='Create wallet']")
                if create_wallet:
                    logger.error('Wallet is not imported')
                    return
            except:
                pass

        except sException.StaleElementReferenceException:
            logger.debug('StaleElement password field')
        except:
            logger.exception('Exception entering password')
    
    try:
        for i in range(2):
            try:
                if i > 0:
                    driver.find_element(By.CLASS_NAME, 'btn-outline-primary').click()

                wallet_icon = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CLASS_NAME, 'okx-wallet-plugin-copy-3'))
                )
                driver.close()
                # Switch to the new tab
                driver.switch_to.window(handles[1])
                return True
            except sException.TimeoutException:
                logger.debug('Timeout when logging in to the wallet')

        driver.close()
        # Switch to the new tab
        driver.switch_to.window(handles[1])
    except:
        logger.exception('Error when logging in to the wallet')
        return

def is_website_logged_in(driver:webdriver.Chrome, logger:logging.Logger)->bool:
    driver.get('https://pioneer.particle.network/en/point')
    login_status=False
    for _ in range(10):
        try:
            time.sleep(1)
            btn = driver.find_element(By.CLASS_NAME,'polygon-btn-text')
            if btn:
                btn_text = btn.text
                if btn_text[:2] == '0X':
                    login_status = True
                    break
        except:
            pass

    return login_status

def task1(driver:webdriver.Chrome, logger:logging.Logger):
    logger.info('Task1 started')
    if not wallet_login(driver, logger):
        if is_website_logged_in(driver, logger):
            logger.debug('Wallet login failed')
            return "Wallet login failed"

    asked_for_authorization = False
    if not is_website_logged_in(driver, logger):
        original_window = driver.window_handles[0]
        if len(driver.window_handles) > 0:
            driver.switch_to.window(driver.window_handles[-1])
            if 'mcohilncbfahbmgdjkbpemcciiolgcge' in driver.current_url:
                try:
                    confirm_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.CLASS_NAME, 'btn-fill-highlight'))
                    )
                    confirm_button.click()
                    time.sleep(5)
                    driver.switch_to.window(original_window)
                    logger.debug('Login request authorized in wallet')
                    asked_for_authorization = True
                except Exception as e: 
                    logger.error(f'Error authorizing login request in wallet: {e}')
                    return "Error authorizing login request in wallet"
            else:
                driver.switch_to.window(original_window)
                logger.debug('Popup is not for okx wallet login')
                return "Website login failed"
        else:
            logger.debug('Website login failed')
            return "Website login failed"
    
    
    if asked_for_authorization:
        if not is_website_logged_in(driver, logger):
            logger.debug('Website login failed')
            return "Website login failed"

    #Task1 Success
    return 0

def wait_for_xhr_request(driver:webdriver.Chrome, url_to_wait_for, event:threading.Event, logger:logging.Logger):
    # Continuously check logs for the desired XHR request
    while not event.is_set():
        logs = driver.get_log('performance')
        for entry in logs:
            if 'Network.responseReceived' in entry['message']:
                message = entry['message']
                if url_to_wait_for in message:
                    event.set()
                    break

def task2(driver:webdriver.Chrome, logger:logging.Logger):
    logger.info('Task2 started')
    original_window = driver.current_window_handle

    # Click deposit button
    try:
        logger.debug('Clicking deposit button')
        deposit_clicked = False
        for _ in range(5): # retry stale element
            time.sleep(1)
            try:
                deposit_button_text = 'Deposit'
                deposit_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, f"//button[.//span[text()='{deposit_button_text}']]"))
                )
                deposit_button.click()
                logger.debug('deposit button clicked')
                deposit_clicked = True
                break
            except sException.TimeoutException:
                logger.debug('Timeout clicking deposit field')
            except:
                logger.exception('Exception clicking deposit button')

        if not deposit_clicked:
            logger.error('Deposit button not found or failed to click')
            return "Deposit button not found or failed to click"
    except:
        logger.exception('Error clicking deposit button')
        return "Error clicking deposit button"
    
    time.sleep(2)
    # Enter deposit amount
    try:
        logger.debug('Entering deposit amount')
        for _ in range(5): # retry stale element
            time.sleep(1)
            try:
                deposit_amount_field = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[placeholder="0.00"]'))
                )
                deposit_amount_field.click()
                time.sleep(0.5)
                TASK2_DEPOSIT_AMOUNT = '0.9'
                deposit_amount_field.send_keys(TASK2_DEPOSIT_AMOUNT)
                time.sleep(2)
                deposit_amount_field.send_keys(Keys.RETURN)
                logger.debug('deposit amount entered')
                break
            except sException.TimeoutException:
                logger.debug('Timeout entering deposit amount')
            except:
                logger.exception('Exception entering deposit amount')
    except:
        logger.exception('Error entering deposit amount')
        return "Error entering deposit amount"
    
    # Confirm payment in wallet
    try:
        logger.debug('Confirming payment in wallet')
        # Switch to the new window
        switched_to_popup = False
        for _ in range(40):
            time.sleep(1)
            if len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[-1])
                switched_to_popup = True
                break
        
        if not switched_to_popup:
            logger.error('Failed to switch to the wallet popup window')
            return "Failed to switch to the wallet popup window"
        
        time.sleep(2)
        
        # Click first confirm button
        try:
            logger.debug('Clicking confirm button')
            first_confirmation = False
            for _ in range(5): # retry stale element
                time.sleep(1)
                try:
                    first_confirmation_button = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.CLASS_NAME, 'btn-fill-highlight'))
                    )
                    first_confirmation_button.click()
                    logger.debug('first confirm button clicked')
                    first_confirmation = True
                    break
                except sException.TimeoutException:
                    logger.debug('Timeout clicking first confirm button')
                except:
                    logger.exception('Exception clicking first confirm button')
            if not first_confirmation:
                logger.error('First confirm button not found or failed to click')
                return "First confirm button not found or failed to click"
        except:
            logger.exception('Error clicking first confirm button')
            return "Error clicking first confirm button"
        
        time.sleep(1)

        # Click second confirm button
        try:
            logger.debug('Clicking second confirm button')
            second_confirmation = False
            second_confirmation_not_asked = False
            for _ in range(5): # retry stale element
                time.sleep(1)
                try:
                    second_confirmation_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.CLASS_NAME, 'btn-fill-highlight'))
                    )
                    second_confirmation_button.click()
                    logger.debug('second confirm button click')
                    second_confirmation = True
                    break
                except sException.TimeoutException:
                    logger.debug('Timeout clicking second confirm button')
                except sException.NoSuchWindowException:
                    logger.debug('Wallet window closed without asking second confirmation')
                    second_confirmation_not_asked = True
                    break
                except:
                    logger.exception('Exception entering second confirm button')
        except:
            logger.exception('Error clicking second confirm button')
            return "Error clicking second confirm button"
    except:
        logger.exception('Error confirming payment in wallet')
        return "Error confirming payment in wallet"
    finally:
        # Switch back to the original window
        driver.switch_to.window(original_window)

    # Wait por deposit to be processed
    try:
        url_to_wait_for = 'https://pioneer-api.particle.network/deposits?timestamp'

        # Create an event to signal when the XHR request is detected
        event = threading.Event()

        # Create and start the thread
        thread = threading.Thread(target=wait_for_xhr_request, args=(driver, url_to_wait_for, event, logger))
        thread.start()

        logger.info('Waiting for payment confirmation request (max 5 minutes)')
        # Main thread can continue working and wait for the event
        event.wait(timeout=300)

        if event.is_set():
            logger.info("Deposit confirmed")
        else:
            logger.error("Timeout waiting for payment confirmation request")
            return "Timeout waiting for payment confirmation request"
    except:
        logger.exception('Error waiting for payment confirmation request')
        return "Error waiting for payment confirmation request"
    
    # Press Back button
    try:
        back_button_clicked = False
        for _ in range(5): # retry stale element
            time.sleep(1)
            try:
                back_button_text = 'back'
                back_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, f"//div[text()='{back_button_text}']"))
                )
                back_button.click()
                back_button_clicked = True
                logger.debug('back button clicked')
                break
            except sException.TimeoutException:
                logger.debug('Timeout clicking back button')
            except:
                logger.exception('Exception in back button')

        # Task2 Success
        if back_button_clicked:
            time.sleep(5) # voluntary wait for amount re be reflected in wallet
            return 0
        else:
            logger.error('Back button not found or failed to click')
            return "Back button not found or failed to click"
    except:
        logger.exception('Error clicking back button')
        return "Error clicking back button"

def task3(driver:webdriver.Chrome, logger:logging.Logger):
    original_window = driver.current_window_handle

    def task3_intermediate():
        # Click open wallet button
        try:
            logger.debug('Clicking open wallet button')
            open_wallet_button_clicked = False
            for _ in range(5): # retry stale element
                time.sleep(1)
                try:
                    open_wallet_button_text = 'Open Wallet'
                    open_wallet_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, f"//button[.//span[text()='{open_wallet_button_text}']]"))
                    )
                    driver.execute_script("arguments[0].scrollIntoView(true);", open_wallet_button)
                    time.sleep(0.5)

                    if open_wallet_button:
                        logger.debug('open_wallet_button found')
                    else:
                        logger.debug('open_wallet_button missing')
                    open_wallet_button.click()
                    logger.debug('open_wallet_button clicked')
                    open_wallet_button_clicked = True
                    break
                except sException.TimeoutException:
                    logger.debug('Timeout clicking open wallet button')
                except:
                    logger.exception('Exception clicking open wallet button')

            if not open_wallet_button_clicked:
                logger.error('open_wallet_button not found or failed to click')
                return "open_wallet_button not found or failed to click"
        except:
            logger.exception('Error clicking open_wallet_button')
            return "Error clicking open_wallet_button"

        # Switch to iframe wallet
        try:
            # Wait for the iframe to be present
            iframe = WebDriverWait(driver, 60).until(
                EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, 'iframe'))
            )
            if iframe:
                logger.debug('Switched to iframe wallet')
        except sException.TimeoutException:
            logger.debug('Timeout switching to iframe wallet')
            return "Timeout switching to iframe wallet"
        except:
            logger.exception('Error switching to iframe wallet')
            return "Error switching to iframe wallet"

        # Copy wallet address and Click send button
        try:
            logger.debug('Clicking send button')
            send_clicked = False
            for _ in range(5): # retry stale element
                time.sleep(1)
                try:
                    # Copy wallet address to clipboard
                    wallet_address_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.CLASS_NAME, 'copy-wrap'))
                    )
                    wallet_address_button.click()
                    time.sleep(0.3)
                    wallet_address = pyperclip.paste()

                    send_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.CLASS_NAME, 'icon-button-default'))
                        )
        
                    if send_button:
                        logger.debug('send found')
                    else:
                        logger.debug('send missing')
                    time.sleep(1)
                    send_button.click()
                    logger.debug('send clicked')
                    send_clicked = True
                    break
                except sException.TimeoutException:
                    logger.debug('Timeout send button step')
                except:
                    logger.exception('Exception clicking send button')
            if not send_clicked:
                logger.error('Send button not found or failed to click')
                return "Send button not found or failed to click"
        except:
            logger.exception('Error clicking send button')
            return "Error clicking send button"
    
        # Click Choose Token Button
        try:
            logger.debug('Clicking choose_token button')
            choose_token_clicked = False
            for _ in range(5): # retry stale element
                time.sleep(1)
                try:
                    choose_token_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.CLASS_NAME, 'choose-token'))
                        )
        
                    if choose_token_button:
                        logger.debug('choose_token button found')
                    else:
                        logger.debug('choose_token button missing')
                    time.sleep(1)
                    choose_token_button.click()
                    logger.debug('choose_token button clicked')
                    choose_token_clicked = True
                    break
                except sException.TimeoutException:
                    logger.debug('Timeout clicking choose token button')
                except:
                    logger.exception('Exception clicking choose token button')
            if not choose_token_clicked:
                logger.error('choose_token button not found or failed to click')
                return "choose_token button not found or failed to click"
        except:
            logger.exception('Error clicking choose_token button')
            return "Error clicking choose_token button"

        # Choose Appropriate Token
        try:
            logger.debug('Choosing USDG token')
            token_item_clicked = False
            for _ in range(5): # retry stale element
                time.sleep(1)
                try:
                    scroll_div = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.CLASS_NAME, 'scrollContainer'))
                        )
                    if not scroll_div:
                        logger.error('scroll_div not found on wallet page')
                        return "scroll_div not found on wallet page"
                    
                    time.sleep(1)
                    token_item_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-key="Ethereum_0_USDG_USDG"]'))
                        )
        
                    if token_item_button:
                        logger.debug('token_item button found')
                    else:
                        logger.debug('token_item button missing')
                    time.sleep(1)
                    token_item_button.click()
                    logger.debug('token_item button clicked')
                    token_item_clicked = True
                    break
                except sException.TimeoutException:
                    logger.debug('Timeout clicking token button')
                except:
                    logger.exception('Exception clicking token button')
            if not token_item_clicked:
                logger.error('token_item button not found or failed to click')
                return "token_item button not found or failed to click"
        except:
            logger.exception('Error clicking token_item button')
            return "Error clicking token_item button"
        
        # Enter wallet address
        try:
            logger.debug('Entering wallet address')
            wallet_address_entered = False
            for _ in range(5):
                try:
                    time.sleep(1)
                    textarea = driver.find_element(By.ID, 'send_to')
                    textarea.click()
                    textarea.send_keys(wallet_address)
                    wallet_address_entered = True
                    break
                except:
                    logger.exception('Exception entering wallet address')
            if not wallet_address_entered:
                logger.error('Failed to enter wallet address')
                return "Failed to enter wallet address"
        except:
            logger.exception('Error entering wallet address')
            return "Error entering wallet address"
        
        # Enter amount
        try:
            logger.debug('Entering amount')
            amount_entered = False
            for _ in range(5):
                try:
                    time.sleep(1)
                    amount_field = driver.find_element(By.ID, 'send_amount')
                    amount_field.click()
                    amount = str(round(random.uniform(0.01, 0.10), 2))
                    amount_field.send_keys(amount)
                    amount_field.send_keys(Keys.RETURN) # Press Enter to submit
                    amount_entered = True
                    break
                except:
                    logger.exception('Exception entering amount')
            if not amount_entered:
                logger.error('Failed to enter amount')
                return "Failed to enter amount"
        except:
            logger.exception('Error entering amount')
            return "Error entering amount"
        
        # Click Send button (Swap)
        try:
            logger.debug('Clicking swap_send button')
            swap_send_button_clicked = False
            for _ in range(5): # retry stale element
                time.sleep(1)
                try:
                    swap_send_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.CLASS_NAME, 'swap-btn'))
                        )
        
                    if swap_send_button:
                        logger.debug('swap_send button found')
                    else:
                        logger.debug('swap_send button missing')

                    swap_send_button.click()
                    logger.debug('swap_send button clicked')
                    swap_send_button_clicked = True
                    break
                except sException.TimeoutException:
                    logger.debug('Timeout clicking swap send button')
                except:
                    logger.exception('Exception clicking swap send button ')

            if not swap_send_button_clicked:
                logger.error('swap_send button not found or failed to click')
                return "swap_send button not found or failed to click"
        except:
            logger.exception('Error clicking swap_send button')
            return "Error clicking swap_send button"
        
        # Solve captcha and confirm payment in OKX wallet
        try:
            logger.debug('Solving captcha and confirming payment in wallet')
            # Confirm payment in wallet
            try:
                # Switch to the new window
                switched_to_popup = False
                WebDriverWait(driver, 60).until(lambda d: len(d.window_handles) > 1) 
                driver.switch_to.window(driver.window_handles[-1])
                switched_to_popup = True
                
                if not switched_to_popup:
                    logger.error('Failed to switch to the wallet popup window')
                    logger.debug('Captcha solver probably failed to solve the captcha')
                    return "Failed to switch to the wallet popup window"
                
                time.sleep(2)
                
                # Click first confirm button
                try:
                    first_confirmation = False
                    for _ in range(5): # retry stale element
                        time.sleep(1)
                        try:
                            first_confirmation_button = WebDriverWait(driver, 20).until(
                                EC.presence_of_element_located((By.CLASS_NAME, 'btn-fill-highlight'))
                            )
                            first_confirmation_button.click()
                            logger.debug('first confirm button click')
                            first_confirmation = True
                            return 0
                        except sException.TimeoutException:
                            logger.debug('Timeout clicking first confirm button')
                        except:
                            logger.exception('Exception clicking first confirm button')
                    if not first_confirmation:
                        logger.error('First confirm button not found or failed to click')
                        return "First confirm button not found or failed to click"
                except:
                    logger.exception('Error clicking first confirm button')
                    return "Error clicking first confirm button"
            except:
                logger.exception('Error confirming payment in wallet')
                return "Error confirming payment in wallet"
        except:
            logger.exception('Error in captcha solver')
            return "Error in captcha solver"
        finally:
            # Switch back to the original window
            driver.switch_to.window(original_window)
    
    for i in range(3):
        task3_intermediate_result = task3_intermediate()
        if task3_intermediate_result == 0:
            break
        elif i == 2:
            return task3_intermediate_result
        else:
            driver.get('https://pioneer.particle.network/en/point')
    # Switch to iframe wallet
    try:
        for _ in range(5): # retry stale element
            time.sleep(1)
            try:
                iframe = WebDriverWait(driver, 20).until(
                    EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, 'iframe'))
                    )
                logger.info('Switched to IFrame wallet')
                break
            except sException.TimeoutException:
                logger.debug('Timeout switching to iframe wallet')
    except:
        logger.exception('Error switching to iframe wallet')
        return "Error switching to iframe wallet"
        
    # Wait for transaction success
    try:
        logger.debug('Waiting for transaction confirmation')
        for _ in range(5): # retry stale element
            time.sleep(1)
            try:
                div = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CLASS_NAME, 'transaction-result-container'))
                    )
                if 'view on block explorer' in div.text.lower():
                    logger.info('Transaction success')
                    break
                else:
                    logger.debug('Waiting for transaction confirmation')
            except sException.TimeoutException:
                logger.debug('Timeout waiting for transaction confirmation')
            except sException.StaleElementReferenceException:
                logger.debug('StaleElement waiting for transaction confirmation')
    except:
        logger.exception('Error waiting for transaction confirmation')
        return "Error waiting for transaction confirmation"

    # Click cross button
    try:
        logger.debug('Clicking cross button')
        for _ in range(5): # retry stale element 
            try:
                cross_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.CLASS_NAME, 'ant-drawer-extra'))
                        )
                cross_button.click()
                break
            except sException.StaleElementReferenceException:
                logger.debug('StaleElement cross popup button')
            except sException.TimeoutException:
                logger.debug('Timeout Clicking cross button')
    except:
        logger.exception('Error Clicking cross button')
        return "Error Clicking cross button"
    finally:
        # Switch back to the main content
        driver.switch_to.default_content()
    
    # Close iframe wallet
    try:
        logger.debug('Closing wallet popup')
        for _ in range(5): # retry stale element 
            try:
                close_popup_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.CLASS_NAME, 'particle-pwe-btn'))
                    )
                close_popup_button.click()
                # TASK3 SUCCESS
                return 0
            except sException.StaleElementReferenceException:
                logger.debug('StaleElement close popup button')
            except sException.TimeoutException:
                logger.debug('Timeout closing wallet popup')
    except:
        logger.exception('Error closing wallet popup')
        return "Error closing wallet popup"

def task4(driver:webdriver.Chrome, logger:logging.Logger):
    original_window = driver.current_window_handle

    # Click Purchase NFT button
    try:
        logger.debug('Clicking Purchase NFT button')
        purchase_nft__button_clicked = False
        for _ in range(5): # retry stale element
            time.sleep(1)
            try:
                purchase_nft__button_text = 'Purchase NFT'
                purchase_nft__button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, f"//button[.//span[text()='{purchase_nft__button_text}']]"))
                )
                driver.execute_script("arguments[0].scrollIntoView(true);", purchase_nft__button)
                time.sleep(0.5)

                if purchase_nft__button:
                    logger.debug('purchase_nft__button found')
                else:
                    logger.debug('purchase_nft__button missing')
                purchase_nft__button.click()
                logger.debug('purchase_nft__button clicked')
                purchase_nft__button_clicked = True
                break
            except sException.TimeoutException:
                logger.debug('Timeout clicking open wallet button')
            except:
                logger.exception('Exception clicking open wallet button')

        if not purchase_nft__button_clicked:
            logger.error('purchase_nft__button not found or failed to click')
            return "purchase_nft__button not found or failed to click"
    except:
        logger.exception('Error clicking purchase_nft__button')
        return "Error clicking purchase_nft__button"

    def task4_intermediate_steps():
        # Click Purchase button
        try:
            logger.debug('Clicking Purchase button')
            purchase__button_clicked = False
            for _ in range(5): # retry stale element
                time.sleep(1)
                try:
                    purchase__button_text = 'Purchase'
                    purchase__button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, f"//button[.//span[text()='{purchase__button_text}']]"))
                    )
                    driver.execute_script("arguments[0].scrollIntoView(true);", purchase__button)
                    time.sleep(0.5)

                    if purchase__button:
                        logger.debug('purchase__button found')
                    else:
                        logger.debug('purchase__button missing')
                    purchase__button.click()
                    logger.debug('purchase__button clicked')
                    purchase__button_clicked = True
                    break
                except sException.TimeoutException:
                    logger.debug('Timeout clicking open wallet button')
                except:
                    logger.exception('Exception clicking open wallet button')

            if not purchase__button_clicked:
                logger.error('purchase__button not found or failed to click')
                return "purchase__button not found or failed to click"
        except:
            logger.exception('Error clicking purchase__button')
            return "Error clicking purchase__button"
        
        # Select USDG Token
        try:
            logger.debug('Clicking USDG token button')
            usdg_token_button_clicked = False
            for _ in range(5): # retry stale element
                time.sleep(1)
                try:
                    usdg_token_button_text = 'usdg'
                    usdg_token_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, f"//div[text()='{usdg_token_button_text}']"))
                    )
                    time.sleep(0.5)

                    if usdg_token_button:
                        logger.debug('usdg_token_button found')
                    else:
                        logger.debug('usdg_token_button missing')
                    usdg_token_button.click()
                    logger.debug('usdg_token_button clicked')
                    usdg_token_button_clicked = True
                    break
                except sException.TimeoutException:
                    logger.debug('Timeout clicking usdg token button')
                except:
                    logger.exception('Exception clicking usdg token button')

            if not usdg_token_button_clicked:
                logger.error('usdg_token_button not found or failed to click')
                return "usdg_token_button not found or failed to click"
        except:
            logger.exception('Error clicking usdg_token_button')
            return "Error clicking usdg_token_button"
        
        # Click Next button
        try:
            logger.debug('Clicking Next button')
            next_button_clicked = False
            for _ in range(5): # retry stale element
                time.sleep(1)
                try:
                    next_button_text = 'Next'
                    next_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, f"//button[.//span[text()='{next_button_text}']]"))
                    )
                    time.sleep(0.5)

                    if next_button:
                        logger.debug('next_button found')
                    else:
                        logger.debug('next_button missing')
                    next_button.click()
                    logger.debug('next_button clicked')
                    next_button_clicked = True
                    break
                except sException.TimeoutException:
                    logger.debug('Timeout clicking next button')
                except:
                    logger.exception('Exception clicking next button')

            if not next_button_clicked:
                logger.error('next_button not found or failed to click')
                return "next_button not found or failed to click"
        except:
            logger.exception('Error clicking next_button')
            return "Error clicking next_button"

        # Click Purchase2 button
        try:
            logger.debug('Clicking Purchase button (2)')
            purchase2_button_clicked = False
            for _ in range(5): # retry stale element
                time.sleep(1)
                try:
                    purchase2_button_text = 'Purchase'
                    purchase2_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, f"//div[@class='react-responsive-modal-modal']//button[.//span[text()='{purchase2_button_text}']]")) #f"//div[.//span[text()='{purchase2_button_text}']]"))
                    )
                    driver.execute_script("arguments[0].scrollIntoView(true);", purchase2_button)
                    time.sleep(1)

                    if purchase2_button:
                        logger.debug('purchase2_button found')
                    else:
                        logger.debug('purchase2_button missing')
                    purchase2_button.click()
                    logger.debug('purchase2_button clicked')
                    purchase2_button_clicked = True
                    return 0
                except sException.TimeoutException:
                    logger.debug('Timeout clicking next button')
                except sException.ElementClickInterceptedException as e:
                    logger.debug(f'Click intercepted, retrying...')
                    time.sleep(1)
                except:
                    logger.exception('Exception clicking next button')

            if not purchase2_button_clicked:
                logger.error('purchase2_button not found or failed to click')
                return "purchase2_button not found or failed to click"
        except:
            logger.exception('Error clicking purchase2_button')
            return "Error clicking purchase2_button"

    intermediate_result = task4_intermediate_steps()
    for i in range(3):
        if intermediate_result == 0:
            break
        elif i == 2:
            return 'Failed please check the logs'
        else:
            driver.refresh()

    # After clicking Purchase2 button we get a captcha before redirecting to wallet confirmation

    # Confirm payment in OKX wallet
    try:
        logger.debug('Confirming payment in wallet')
        try:
            # Switch to the new window
            switched_to_popup = False
            counter = 0
            while True:# Wait for captcha get solved and eventually new window appear
                counter +=1
                if counter % 60 == 0:
                    driver.refresh()
                    task4_intermediate_steps()
                time.sleep(1)
                if len(driver.window_handles) > 1:
                    driver.switch_to.window(driver.window_handles[-1])
                    switched_to_popup = True
                    break
            if not switched_to_popup:
                logger.error('Failed to switch to the wallet popup window')
                logger.debug('Captcha solver probably failed to solve the captcha')
                return "Failed to switch to the wallet popup window"
            
            time.sleep(2)
            
            # Click first confirm button
            try:
                first_confirmation = False
                for _ in range(5): # retry stale element
                    time.sleep(1)
                    try:
                        first_confirmation_button = WebDriverWait(driver, 20).until(
                            EC.presence_of_element_located((By.CLASS_NAME, 'btn-fill-highlight'))
                        )
                        first_confirmation_button.click()
                        logger.debug('first confirm button click')
                        first_confirmation = True
                        break
                    except sException.TimeoutException:
                        logger.debug('Timeout clicking first confirm button')
                    except:
                        logger.exception('Exception clicking first confirm button')
                if not first_confirmation:
                    logger.error('First confirm button not found or failed to click')
                    return "First confirm button not found or failed to click"
            except:
                logger.exception('Error clicking first confirm button')
                return "Error clicking first confirm button"
        except:
            logger.exception('Error confirming payment in wallet')
            return "Error confirming payment in wallet"
    except:
        logger.exception('Error in captcha solver')
        return "Error in captcha solver"
    finally:
        # Switch back to the original window
        driver.switch_to.window(original_window)
    
    # Wait for transaction success
    try:
        logger.debug('Waiting for transaction confirmation')
        for _ in range(5): # retry stale element
            time.sleep(1)
            try:
                div_text = 'successfully'
                # Wait until the element with the class "react-responsive-modal-modal" contains the text "successfully", case insensitive
                WebDriverWait(driver, 30).until(
                    lambda driver: div_text.lower() in driver.find_element(By.CLASS_NAME, "react-responsive-modal-modal").text.lower()
                )
                logger.info('Transaction success')
                break
            except sException.TimeoutException:
                logger.debug('Timeout waiting for transaction confirmation')
            except sException.StaleElementReferenceException:
                logger.debug('StaleElement waiting for transaction confirmation')
    except:
        logger.exception('Error waiting for transaction confirmation')
        return "Error waiting for transaction confirmation"
    
    # Close transaction confirmation popup
    try:
        close_button = None
        logger.debug('Closing nft transaction confirmation popup')
        for _ in range(5): # retry stale element
            time.sleep(1)
            try:
                close_button = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CLASS_NAME, 'react-responsive-modal-closeButton'))
                )
                close_button.click()
                logger.debug('nft buy confirmation popup closed')
                break
            except sException.TimeoutException:
                logger.debug('Timeout closing nft transaction confirmation popup')
            except:
                logger.exception('Exception closing nft transaction confirmation popup')
        if not close_button:
            logger.error('nft transaction confirmation popup not found or failed to click')
            return 'nft transaction confirmation popup not found or failed to click'

    except:
        logger.exception('Error closing nft transaction confirmation popup')
        return "Error closing nft transaction confirmation popup"

    # Press Back button
    try:
        back_button_clicked = False
        for _ in range(5): # retry stale element
            time.sleep(1)
            try:
                back_button_text = 'back'
                back_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, f"//div[text()='{back_button_text}']"))
                )
                back_button.click()
                back_button_clicked = True
                logger.debug('back button clicked')
                break
            except sException.TimeoutException:
                logger.debug('Timeout clicking back button')
            except:
                logger.exception('Exception in back button')

        if back_button_clicked:
            time.sleep(5) # voluntary wait for smooth transition
            # TASK4 SUCCESS
            return 0
        else:
            logger.error('Back button not found or failed to click')
            return "Back button not found or failed to click"
    except:
        logger.exception('Error clicking back button')
        return "Error clicking back button"

def main(profile, logger:logging.Logger):
    try:
        logger.info(f'Opening Browser Profile: {profile["integer_id"]}')
        driver = open_browser_profile(profile['alphanumeric_id'], logger)
        if isinstance(driver, webdriver.Chrome):
            original_window = driver.current_window_handle
            # Close all other tabs/windows
            for handle in driver.window_handles:
                if handle != original_window:
                    driver.switch_to.window(handle)
                    driver.close()

            # Switch back to the original window
            driver.switch_to.window(original_window)

            task1_success = task1(driver, logger)
            if task1_success==0:
                logger.info('Task1 Success')
            else:
                logger.error('Task1 Failure')
                return f"Task1 Failure\n{task1_success}" 
            
            if CONFIG['SHOULD_RUN_TASK2'].lower().strip() == 'yes':
                max_tries = 3
                task2_success = None
                while max_tries > 0:
                    max_tries -= 1
                    task2_success = task2(driver, logger)
                    if task2_success==0:
                        logger.info('Task2 Success')
                        break
                    else:
                        logger.error('Task2 Failure - Retrying')
                        driver.get('https://pioneer.particle.network/en/point')
                    
                if not task2_success==0:
                    return f"Task2 Failure\n{task2_success}"

            # Task3 run 10 times
            if CONFIG['SHOULD_RUN_TASK3'].lower().strip() == 'yes':
                task3_successes = 0
                max_tries = 20 #so each profile get 2 chances
                while task3_successes < 10 and max_tries > 0:
                    max_tries -= 1
                    task3_success = task3(driver, logger)
                    if task3_success==0:
                        logger.info(f'Task3 RUN-{task3_successes} Success')
                        task3_successes += 1
                    else:
                        logger.error(f'Task3 RUN-{task3_successes} Failure')
                        driver.get('https://pioneer.particle.network/en/point')
                
                if task3_successes < 10:
                    logger.error('Task3 Failed to execute 10 times')
                    return "Task3 Failed to execute 10 times"
                
            # voluntary wait for transaction to be reflected in wallet
            time.sleep(10)

            # Task4 run 5 times
            if CONFIG['SHOULD_RUN_TASK4'].lower().strip() == 'yes':
                task4_successes = 0
                max_tries = 10 #so each profile get 2 chances
                while task4_successes < 5 and max_tries > 0:
                    max_tries -= 1
                    task4_success = task4(driver, logger)
                    if task4_success==0:
                        logger.info(f'Task4 RUN-{task4_successes} Success')
                        task4_successes += 1
                    else:
                        logger.error(f'Task4 RUN-{task4_successes} Failure')
                        driver.get('https://pioneer.particle.network/en/point')
                
                if task4_successes < 5:
                    logger.error('Task4 Failed to execute 5 times')
                    return "Task4 Failed to execute 5 times"
        else:
            logger.debug('Failed to open browser')
            return "Failed to open browser"        
        return "SUCCESS"
    
    except Exception as e:
        logger.exception('Exception occurred')
        return str(e)
    finally:
        try:
            close_browser_profile(profile['alphanumeric_id'], driver, logger)
            logger.debug('Browser Closed Successfully')
        except:
            logger.debug('Error closing browser')

def run_profile(profile):
    run_id = str(uuid.uuid4())
    log_file = os.path.join(logs_dir, f"{run_id}.log")
    
    # Set up a custom logger for this specific profile run
    custom_logger = setup_logger(log_file)
    
    custom_logger.info(f'Starting run for profile: {profile["integer_id"]}')
    result = main(profile, custom_logger)
    custom_logger.info(f'Completed run for profile: {profile["integer_id"]} with result: {result}')
    
    return {"Profile ID": profile['integer_id'], "Run ID": run_id, "Result": result}

if __name__ == '__main__':
    # logger.debug('Started')
    # profiles = get_profiles()
    report = [{"Profile ID": 1, "Run ID": 1, "Result": 1}]

    # with ThreadPoolExecutor(max_workers=5) as executor:
    #     futures = {executor.submit(run_profile, profile): profile for profile in profiles}
        
    #     for future in as_completed(futures):
    #         report.append(future.result())


    def rotate_reports():
        _latest = os.path.join(reports_dir, 'report.csv')
        latest = os.path.join(reports_dir, 'latest-report.csv')
        recent = os.path.join(reports_dir, 'recent-report.csv')
        old = os.path.join(reports_dir, 'old-report.csv')

        # Rotate the reports to keep the last 3
        if os.path.exists(old):
            os.remove(old)
        if os.path.exists(recent):
            os.rename(recent, old)
        if os.path.exists(latest):
            os.rename(latest, recent)
        if os.path.exists(_latest):
            os.rename(_latest, latest)

    # Write the report to a CSV file
    file_path = os.path.join(reports_dir, 'report.csv')
    with open(file_path, mode='w', newline='') as file:
        fieldnames = ['Profile ID', 'Run ID', 'Result']
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report)

    # preserve the last 3 reports
    rotate_reports()

    print("Report has been generated: latest-report.csv")

