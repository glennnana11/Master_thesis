import datetime
import time
import logging
import os
import paramiko
import subprocess

# Constants and Configuration
FTP_SERVER = "ssh.server.com"
FTP_PORT = 22  # Change this to the actual port if it's different
FTP_USERNAME = "username@server.com"
FTP_PASSWORD = "user_password"
FTP_DIRECTORY = "/image_directory/"
CAPTURE_INTERVAL = 300  # 300 seconds
LOCAL_DIRECTORY = "your_local_directory"
COUNTER_FILE = "image_counter.txt"
MAX_RETRY_ATTEMPTS = 4

# Ensure the local directory exists
os.makedirs(LOCAL_DIRECTORY, exist_ok=True)

# Configure logging to save logs to a file
log_file = "log_analysis.txt"
logging.basicConfig(filename=log_file, level=logging.INFO)
logger = logging.getLogger(__name__)

def load_image_counter():
    try:
        with open(COUNTER_FILE, 'r') as counter_file:
            return int(counter_file.read().strip())
    except FileNotFoundError:
        return 1

def save_image_counter(counter):
    with open(COUNTER_FILE, 'w') as counter_file:
        counter_file.write(str(counter))

def initialize_sftp_session():
    try:
        transport = paramiko.Transport((FTP_SERVER, FTP_PORT))
        transport.connect(username=FTP_USERNAME, password=FTP_PASSWORD)
        session = paramiko.SFTPClient.from_transport(transport)
        logger.info("SFTP session initialized successfully.")
        return session
    except Exception as e:
        logger.error(f"Error during SFTP session initialization: {str(e)}")
        return None

def upload_to_ftp_sftp(session, local_filename, image_name):
    try:
        remote_path = os.path.join(FTP_DIRECTORY, image_name)
        session.put(local_filename, remote_path)
        logger.info(f"Image successfully sent to the FTP server (SFTP): {image_name}")
        return True
    except paramiko.SSHException as ssh_exception:
        logger.error(f"SSHException: {ssh_exception}")
        return False
    except Exception as e:
        logger.error(f"Error during SFTP upload: {str(e)}")
        return False

def retry_failed_uploads(session, failed_uploads, image_counter):
    for failed_upload in failed_uploads.copy():
        local_filename, image_name, retry_count = failed_upload
        upload_successful = upload_to_ftp_sftp(session, local_filename, image_name)
        if upload_successful:
            logger.info(f"Retry attempt {retry_count + 1}/{MAX_RETRY_ATTEMPTS} for {image_name} successful")
            save_image_counter(image_counter)
            image_counter += 1
            failed_uploads.remove(failed_upload)
        else:
            if retry_count < MAX_RETRY_ATTEMPTS:
                logger.warning(f"Retry attempt {retry_count + 1}/{MAX_RETRY_ATTEMPTS} for {image_name}")
                failed_uploads.remove(failed_upload)
                failed_uploads.append((local_filename, image_name, retry_count + 1))
            else:
                logger.error(f"Max retry attempts reached for {image_name}. Upload failed.")

def capture_and_send(image_counter):
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        image_name = f"IMG_{image_counter}_{timestamp}.jpg"
        local_filename = os.path.join(LOCAL_DIRECTORY, image_name)

        # Capture an image using libcamera-still
        subprocess.run(["libcamera-still", "-o", local_filename], check=True)

        logger.info("Image captured")
        return local_filename, image_name
    except subprocess.CalledProcessError as e:
        logger.error(f"Error capturing image: {e}")
        return None, None
    except Exception as e:
        logger.exception(f"An unexpected error occurred: {str(e)}")
        return None, None

def cleanup_local_directory():
    try:
        files = os.listdir(LOCAL_DIRECTORY)
        for file in files:
            file_path = os.path.join(LOCAL_DIRECTORY, file)
            if os.path.isfile(file_path) and time.time() - os.path.getmtime(file_path) > 172800:
                os.remove(file_path)
                logger.info(f"Old local image removed: {file_path}")
    except Exception as e:
        logger.error(f"Error during local directory cleanup: {str(e)}")

def main():
    session = initialize_sftp_session()
    if not session:
        logger.error("SFTP session initialization failed. Exiting...")
        return

    image_counter = load_image_counter()
    failed_uploads = []

    try:
        while True:
            try:
                local_filename, image_name = capture_and_send(image_counter)
                if local_filename and image_name:
                    upload_successful = upload_to_ftp_sftp(session, local_filename, image_name)
                    if upload_successful:
                        save_image_counter(image_counter)
                        image_counter += 1  # Increment the counter
                    else:
                        # Retry upload in the next iteration
                        failed_uploads.append((local_filename, image_name, 1))
            except paramiko.SSHException as ssh_exception:
                logger.error(f"SSHException: {ssh_exception}")
                time.sleep(60)
                continue

            cleanup_local_directory()
            time.sleep(CAPTURE_INTERVAL)

            # Retry failed uploads in the next iteration
            retry_failed_uploads(session, failed_uploads, image_counter)
    finally:
        if session is not None:
            session.close()

if __name__ == "__main__":
    main()
