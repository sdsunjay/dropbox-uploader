import os
import random
import configparser
import dropbox
from dropbox.oauth import DropboxOAuth2FlowNoRedirect

APP_CREATE_URL = "https://www.dropbox.com/developers/apps"
CONFIG_FILE = "config.ini"


def update_config_with_tokens(oauth_result, config_file=CONFIG_FILE):
    # Assuming auth_flow.finish(auth_code) returns an object with the following attributes
    access_token = oauth_result.access_token
    refresh_token = oauth_result.refresh_token
    expires_at = oauth_result.expires_at

    config = configparser.ConfigParser()

    # Read the existing config file
    try:
        config.read(config_file)
    except Exception as e:
        print(f"Failed to read configuration file {config_file}: {e}")
        return

    if "Dropbox" not in config:
        config["Dropbox"] = {}

    # Update the 'Dropbox' section with new tokens
    if access_token:
        print("Access token:", access_token)
        config["Dropbox"]["AccessToken"] = access_token
    if refresh_token:
        print("Refresh token:", refresh_token)
        config["Dropbox"]["RefreshToken"] = refresh_token
    if expires_at:
        print("Expires at:", expires_at)
        config["Dropbox"]["ExpiresAt"] = str(expires_at)
        config["Dropbox"]["ExpirationTime"] = expires_at.isoformat()

    # Write the updated configuration back to the file
    try:
        with open(config_file, "w") as configfile:
            config.write(configfile)
        print(f"Configuration updated with tokens in {config_file}")
    except Exception as e:
        print(f"Failed to write configuration to {config_file}: {e}")
    return access_token


def get_and_store_refresh_token(app_key):
    # Step 1: Start the OAuth 2.0 flow with token_access_type='offline'
    auth_flow = DropboxOAuth2FlowNoRedirect(
        app_key, use_pkce=True, token_access_type="offline"
    )
    authorize_url = auth_flow.start()
    print(f"1. Go to: {authorize_url}")
    print('2. Click "Allow" (you might have to log in first).')
    print("3. Copy the authorization code.")
    auth_code = input("Enter the authorization code here: ").strip()

    # Step 2: Finish the OAuth 2.0 flow and get an access token and a refresh token
    try:
        oauth_result = auth_flow.finish(auth_code)
        update_config_with_tokens(oauth_result)
    except dropbox.oauth.BadRequestException as e:
        print("Bad request error:", e)
    except dropbox.oauth.BadStateException as e:
        print("Bad state error:", e)
    except dropbox.oauth.CsrfException as e:
        print("CSRF error:", e)
    except dropbox.oauth.NotApprovedException as e:
        print("Not approved error:", e)
    except dropbox.oauth.ProviderException as e:
        print("Provider error:", e)
    except Exception as e:
        print("Error in OAuth 2.0 flow:", e)
        exit(1)

    return oauth_result.refresh_token


def prompt(message):
    response = input(f"\n{message}").strip()
    while len(response) < 5:
        print("Input must be at least 5 characters long. Please try again.")
        response = input(f"{message}").strip()
    return response


def write_to_config(app_key, app_secret, access_code=None, config_file=CONFIG_FILE):
    config = configparser.ConfigParser()
    if access_code:

        config["Dropbox"] = {
            "AppKey": app_key,
            "AppSecret": app_secret,
            "AccessCode": access_code,
        }
    else:
        config["Dropbox"] = {
            "AppKey": app_key,
            "AppSecret": app_secret,
        }

    with open(config_file, "w") as configfile:
        config.write(configfile)
    print(f"Configuration written to {config_file}")


def read_from_config(config_file=CONFIG_FILE):
    config = configparser.ConfigParser()

    try:
        config.read(config_file)
    except Exception as e:
        print(f"Failed to read configuration file {config_file}: {e}")
        return None

    if "Dropbox" in config:
        app_key = config.get("Dropbox", "appkey", fallback=None)
        refresh_token = config.get("Dropbox", "refreshtoken", fallback=None)
        return app_key, refresh_token


def refresh_access_token_if_needed(dbx):
    try:
        dbx.check_and_refresh_access_token()
    except dropbox.exceptions.AuthError as err:
        print("Error refreshing access token:", err)


def auth():
    if not os.path.exists(CONFIG_FILE) or os.path.getsize(CONFIG_FILE) == 0:
        print(
            "\n This is the first time you run this script, please follow the instructions:\n"
        )
        print("(note: Dropbox will change their API on 2021-09-30.")
        print(
            "When using dropbox_uploader.sh configured in the past with the old API,"
            " have a look at README.md, before continue.)\n"
        )
        print(
            f" 1) Open the following URL in your Browser, and log in using your account: {APP_CREATE_URL}"
        )
        print(' 2) Click on "Create App", then select "Choose an API: Scoped Access"')
        print(' 3) "Choose the type of access you need: App folder"')
        print(
            f' 4) Enter the "App Name" that you prefer (e.g. MyUploader{random.randint(1000, 9999)}{random.randint(1000, 9999)}{random.randint(1000, 9999)}), must be unique\n'
        )
        print(' Now, click on the "Create App" button.\n')
        print(
            '5) Now the new configuration is opened, switch to tab "permissions" and check '
            '"files.metadata.read/write" and "files.content.read/write"'
        )
        print(' Now, click on the "Submit" button.\n')
        print(' 6) Now to tab "settings" and provide the following information:\n')

        app_key = prompt("App key: ")
        app_secret = prompt("App secret: ")
        write_to_config(app_key, app_secret)
        refresh_token = get_and_store_refresh_token(app_key)

    else:
        app_key, refresh_token = read_from_config()
    if app_key and refresh_token:
        print("\nConfiguration loaded from file:")
        print(f" > App key: {app_key}")
        dbx = dropbox.Dropbox(oauth2_refresh_token=refresh_token, app_key=app_key)
        refresh_access_token_if_needed(dbx)
        return dbx
    else:
        print(
            f"Configuration file is missing required values."
            f" Please delete the config file ({CONFIG_FILE}) and rerun the script."
        )
        exit(1)


if __name__ == "__main__":
    auth()
