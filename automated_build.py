import argparse
import configparser
import os, sys, errno, stat, datetime, time
import logging
import subprocess
import shutil
import smtplib


class CommandExecutionError(Exception):
    def __init__(self, message, command, stdout, stderr, return_code):
        self.message = message
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_file", required=True)
    args = parser.parse_args()
    return args


def load_configurations(config_file):
    logging.info('Loading configurations from file: {}'.format(config_file))

    config_parser = configparser.ConfigParser()
    config_parser.read(config_file)

    validate_configurations(config_parser)

    logging.info('Loading configurations complete')
    return config_parser


def validate_configurations(config_parser):
    try:
        x = config_parser['smtp-conf']['smtp_ssl_host']
        x = config_parser['smtp-conf']['smtp_ssl_port']
        x = config_parser['smtp-conf']['sender']
        x = config_parser['smtp-conf']['password']
        x = config_parser['smtp-conf']['receiver']
        x = config_parser['other-conf']['build_script_file']
        x = config_parser['other-conf']['binary_directory']
    except KeyError as ex:
        logging.error('Configuration not found: {}'.format(ex.args[0]))
        raise


def remove_old_log_files(log_directory):
    current_time = time.time()

    for f in os.listdir(log_directory):
        file_full_path = log_directory + '/' + f
        creation_time = os.path.getctime(file_full_path)
        date_diff = (current_time - creation_time) // (24 * 3600)

        if date_diff >= 7:
            os.unlink(file_full_path)
            logging.info('Removed old log file: {}'.format(file_full_path))


def setup_logging(log_directory):
    # Create log directory
    if not os.path.exists(log_directory):
        os.makedirs(log_directory)

    # Set log filename
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d__%H-%M-%S')
    log_filename = log_directory + '/' + timestamp + '_build' + '.log'

    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_filename), logging.StreamHandler()],
        level=logging.INFO
    )

    logging.info('Setting up logger complete')
    return log_filename


def handle_remove_read_only_error(func, path, exc):
    if not os.access(path, os.W_OK):  # Is the error an access error ?
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        raise


def pull_from_repository():
    logging.info('Pulling from repository')
    execute_command(['git', 'pull'])
    logging.info('Pulling from repository successful')


def run_build_script(configs):
    build_script_file = configs['other-conf']['build_script_file']

    # Give execute permission to build script
    st = os.stat(build_script_file)
    os.chmod(build_script_file, st.st_mode | stat.S_IEXEC)

    logging.info('Running build script')
    execute_command(['./' + build_script_file], 'logs/build_script.log')
    logging.info('Build script completed successfully')


def push_artifacts(configs):
    binary_dir = configs['other-conf']['binary_directory']

    logging.info('Git staging build artifacts in binary directory')
    execute_command(['git', 'stage', binary_dir])
    logging.info('Git staging build artifacts in binary directory successful')

    logging.info('Git commiting build artifacts')
    commit_message = "Add latest build artifacts"
    try:
        execute_command(['git', 'commit', '-m', commit_message])
    except CommandExecutionError as ex:
        if "nothing added to commit" in ex.stdout or \
            "no changes added to commit" in ex.stdout:  # No change to binary files since last commit; ignore this error
            pass
        else:
            raise
    logging.info('Git commiting build artifacts successful')

    logging.info('Git pushing build artifacts')
    execute_command(['git', 'push'], None)
    logging.info('Git pushing build artifacts successful')


def execute_command(command, output_redirect_filename=None):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    stdoutput, stderroutput = process.communicate()

    # Decode to UTF-8, because process.communicate returns byte variables
    if stdoutput:
        stdoutput = stdoutput.decode("utf-8")
        logging.info("\t{}".format(stdoutput))
    if stderroutput:
        stderroutput = stderroutput.decode("utf-8")
        logging.error("\t{}".format(stderroutput))

    if output_redirect_filename:
        with open(output_redirect_filename, "w") as file:
            if stdoutput:
                file.write(stdoutput)
            if stderroutput:
                file.write(stderroutput)

    return_code = process.returncode

    if return_code != 0:
        raise CommandExecutionError("Failed to execute command", " ".join(command),
                                    stdoutput, stderroutput, return_code)


def send_email_about_failure(configs, log_filename):
    email_message = create_email_message(configs, log_filename)
    # print(email_message)
    send_email(email_message, configs)


def create_email_message(configs, log_filename):
    from_str = 'From: ' + configs['smtp-conf']['sender']
    to_str = 'To: ' + configs['smtp-conf']['receiver']
    subject_str = 'Subject: Automated build failed'

    message_body = '\n\nThis message was generated by the automated build script, ' \
                   'because the build script failed. Log file content is printed below.\n\n'

    message_body = message_body + '---------------------------------------------------\n\n'

    with open(log_filename, 'r',encoding='utf8') as file:
        log_file_data = file.read()
        log_file_data = log_file_data.encode("ascii", errors="ignore")
        log_file_data = log_file_data.decode("ascii", errors="ignore")
        print(type(log_file_data))

    message_body = message_body + log_file_data

    message_body = message_body + '---------------------------------------------------\n\n'

    message = '\r\n'.join([
        from_str,
        to_str,
        subject_str,
        '',
        message_body
    ])

    return message


def send_email(email_message, configs):
    sender = configs['smtp-conf']['sender']
    password = configs['smtp-conf']['password']
    receivers = [configs['smtp-conf']['receiver']]
    smtp_server_address = configs['smtp-conf']['smtp_ssl_host']
    smtp_port = configs['smtp-conf']['smtp_ssl_port']

    try:
        server = smtplib.SMTP(smtp_server_address, int(smtp_port))
        server.starttls()

        logging.info('Logging into: {} to send email'.format(sender))
        server.ehlo()
        server.login(sender, password)
        logging.info('Logged into: {}'.format(sender))

        logging.info('Sending email to: {} since automated build failed'.format(receivers))
        server.sendmail(sender, receivers, email_message)
        server.close()
        logging.info('Successfully sent email to: {}'.format(receivers))

    except smtplib.SMTPException as ex:
        logging.exception("Error: unable to send email")


def cleanup(configs):
    logging.info('Cleanup: (nothing to clean)')


def run_automated_build(configs, log_filename):
    try:
        pull_from_repository()
        run_build_script(configs)
        push_artifacts(configs)

    except CommandExecutionError as ex:
        send_email_about_failure(configs, log_filename)
        logging.exception('Exception occurred while running automated build script')

    cleanup(configs)


if __name__ == "__main__":
    args = parse_args()
    config_file = args.config_file
    try:
        log_directory = 'logs'
        log_filename = setup_logging(log_directory)
        remove_old_log_files(log_directory)
        configs = load_configurations(config_file)
        run_automated_build(configs, log_filename)
    except FileNotFoundError:
        logging.critical("File: {} not found".format(config_file))
        logging.exception('Exception occurred while loading configurations')
    except Exception as ex:
        logging.exception('Exception occurred while running build')
        raise
