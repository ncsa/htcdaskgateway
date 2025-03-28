from __future__ import annotations

import getpass
import grp
import re
import stat
import sys
import time
from pathlib import Path

import pexpect


def extract_htcondor_token(text):
    # Pattern to match HTCondor tokens: starts with "ey" and is about 280 chars
    pattern = r"(ey[A-Za-z0-9._-]{277,283})"  # Allowing slight variation in length
    match = re.search(pattern, text)
    if match:
        return match.group(1)
    return None


def main():
    print(
        "This script will help you set up your HTCondor token for the Campus Cluster."
    )
    # Get the current username
    username = getpass.getuser()
    print(f"Using username: {username}")

    # Make sure the user is enrolled in the HTCondor system
    enrolled = True
    try:
        group = grp.getgrnam("inv-HTC")
        if username in group.gr_mem:
            enrolled = True
    except KeyError:
        print("Group inv-HTC not found.")

    if not enrolled:
        print(f"User {username} is not enrolled in the HTCondor system.")
        print(
            "Please complete form https://forms.gle/Mqp5EFb9vgTUSJ876 and try again after approval."
        )
        return 1

    password = getpass.getpass("Password: ")  # This will prompt for password securely

    # SSH connection details
    host = "htc-login.campuscluster.illinois.edu"

    # Start the ssh process
    # Start the ssh process with automatic host key acceptance
    ssh_command = f"ssh -o StrictHostKeyChecking=no {username}@{host}"

    child = pexpect.spawn(ssh_command)

    # Enable logging to see what's happening (optional, remove in production)
    # child.logfile = sys.stdout.buffer

    # Wait for password prompt and send password
    child.expect("Password: ")
    child.sendline(password)

    # Wait for Duo prompt and select option 1
    child.expect(r"Passcode or option \(1-2\): ")
    child.sendline("1")

    print("Requesting Duo authentication...")
    # Give the authentication time to process
    time.sleep(2)

    # Give the authentication time to process and wait for success message
    child.expect(f"{username}@.*[$#] ")  # This pattern should match your shell prompt

    # Now run the condor_token_fetch command
    child.sendline("condor_token_fetch -name htc-login1.campuscluster.illinois.edu")

    # Wait for the command to complete and capture its output
    child.expect(
        rf"\[{username}@.*[$#] "
    )  # This pattern should match your shell prompt

    # Handle the output with error handling for decoding
    try:
        token_output = child.before.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        # Alternative approach if the above still fails
        token_output = child.before.decode("latin-1")  # Try a more permissive encoding

    # Extract just the token text from the output
    # We're assuming the token is the entire output after removing command echoes
    token_lines = token_output.split("\n")

    # Skip the first line which contains the command itself
    token = "\n".join(token_lines[1:]).strip()

    # Extract the token using a regular expression
    token = extract_htcondor_token(token)

    if not token:
        print("Unable to find token. You will need to do this manually.")
        return 1

    # Create the ~/.condor/tokens.d directory structure locally
    condor_dir = Path.expanduser(Path("~/.condor"))
    tokens_dir = condor_dir / Path("tokens.d")

    # Create directories if they don't exist
    Path.mkdir(tokens_dir, parents=True, exist_ok=True)

    # Write the token to the file
    token_file = tokens_dir / Path("htc-login1.campuscluster.illinois.edu")
    with Path.open(token_file, "w") as f:
        f.write(token)

    # Set permissions to 600 (user read/write only, no permissions for group or others)
    Path.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR)
    print(f"Token saved to {token_file} with user-only permissions (600)")

    # Write the condor_config file
    config_content = """
    CONDOR_HOST=htc-login1.campuscluster.illinois.edu
    COLLECTOR_HOST=htc-login1.campuscluster.illinois.edu
    SEC_CLIENT_AUTHENTICATION_METHODS=FS,FS_REMOTE,IDTOKENS
    SCHEDD_HOST=htc-login1.campuscluster.illinois.edu
    """

    config_file = condor_dir / Path("condor_config")
    with Path.open(config_file, "w") as f:
        f.write(config_content)

    print("Please add this to your ~/.bashrc or ~/.bash_profile:")
    print(f"export CONDOR_CONFIG={config_file}")
    # Close the SSH session
    child.sendline("exit")

    return 0


if __name__ == "__main__":
    sys.exit(main())
