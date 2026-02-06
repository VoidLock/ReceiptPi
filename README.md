# Ntfy Receipt Printer

This project is a Python service that subscribes to the [ntfy.sh](https://ntfy.sh) *or selfhosted ntfy server* topic and prints received messages to a connected USB thermal receipt printer.

## Purpose

This service was designed for:
*   Creating a physical notification system.
*   Printing messages received from an ntfy topic.
*   Serving as a simple order ticket system.

## Development Hardware

The service was developed and tested on the following hardware:

*   **Board:** Orange Pi Zero 2W (4GB RAM)
*   **OS:** DietPi (minimal image)
*   **Printer:** A standard USB ESC/POS thermal printer.

## Prerequisites

Ensure the following are installed on your system:

```bash
# For Debian/Ubuntu-based systems (e.g., DietPi):
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git
```

## Manual Execution (Temporary Run)

These steps describe how to run the service directly for testing or temporary use.

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/ntfy-receipt-printer.git
cd ntfy-receipt-printer
```

### 2. Set Up Python Environment

Create and activate a Python virtual environment, then install required packages.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configuration

Configure the service parameters using an `.env` file.

*   **Create `.env`:**
    ```bash
    cp .env.template .env
    ```
*   **Edit `.env`:** Open the `.env` file and set the following variables:
    *   `NTFY_HOST`: The URL of your ntfy server (e.g., `https://ntfy.sh`).
    *   `NTFY_TOPIC`: The ntfy topic to subscribe to.
    *   `PRINTER_VENDOR`: The USB Vendor ID of your thermal printer.
    *   `PRINTER_PRODUCT`: The USB Product ID of your thermal printer.

    To find your printer's Vendor and Product IDs, use the `lsusb` command.

### 4. Run the Service

Ensure your virtual environment is active.

```bash
python app.py
```

Messages sent to the configured ntfy topic will now be printed. Press `Ctrl+C` to stop the service.

#### Command-Line Flags

The `app.py` script supports the following command-line flags:

```
venv ❯ python3 app.py --help
usage: app.py [-h] [--host HOST] [--topic TOPIC] [--calibrate] [--test-align] [--preview]
              [--example {text,kanban}]

Receipt printer listening to an ntfy topic

options:
  -h, --help            show this help message and exit
  --host HOST           ntfy host (including scheme)
  --topic TOPIC         ntfy topic name
  --calibrate           print calibration grid to determine printable area
  --test-align          print alignment test and exit
  --preview, -p         preview mode - show images instead of printing
  --example, -e {text,kanban}
                        show example message
```
### Flag Descriptions
*   `--host <URL>`: Specify the ntfy host URL (e.g., `https://ntfy.example.com`). Overrides `NTFY_HOST` from `.env`.
*   `--topic <NAME>`: Specify the ntfy topic name. Overrides `NTFY_TOPIC` from `.env`.
*   `--calibrate`: Prints a calibration grid to help determine the printable area and adjust printer settings. The script will output instructions for using the grid.
*   `--test-align`: Prints an alignment test message and exits.
*   `--preview`, `-p`: Runs in preview mode, displaying images in a window instead of sending them to the printer. Useful for testing without consuming thermal paper. Terminal will open image in any image viewer as a preview.
*   `--example <TYPE>`, `-e <TYPE>`: Prints an example message of the specified type (`text` or `kanban`) and exits.

### Calibrating the Print Bounding Box

To optimize printing for your specific thermal printer and paper, you can use the built-in calibration feature:

1.  **Run Calibration:** With your printer connected and the virtual environment active, execute the calibration command:
    ```bash
    python app.py --calibrate
    ```
2.  **Inspect Printout:** The printer will output a calibration grid. Examine it carefully:
    *   Note the rightmost column letter that is clearly visible.
    *   Observe if the text is centered or shifted to one side.
3.  **Adjust `.env` Variables:** Based on your observations, modify the following variables in your `.env` file:
    *   `X_OFFSET_MM`: Adjusts the horizontal centering. Use negative values to shift left, positive to shift right.
    *   `SAFE_MARGIN_MM`: Defines the margin from the paper's edge. Increase this if the right edge of your printout is cut off.
    *   `MAX_HEIGHT_MM`: (Optional) Sets a maximum height for receipts in millimeters.

    *Example .env adjustments:*
    ```
    X_OFFSET_MM=2
    SAFE_MARGIN_MM=5
    # MAX_HEIGHT_MM=150
    ```
    Repeat the calibration process until you are satisfied with the print alignment and bounding box.

## Systemd Service Installation (Permanent Run)

To install the service to run automatically on system boot, use the provided installer script.

**Note:** This script requires `sudo` privileges.

```bash
sudo ./scripts/install_service.sh $(pwd) $(whoami)
```

This script performs the following actions:
1.  Copies a systemd service file to `/etc/systemd/system/`.
2.  Creates a default environment file at `/etc/default/receipt-printer` using values from your project's `.env` file.
3.  Enables and starts the `receipt-printer` service.

Check the service status with:

```bash
systemctl status receipt-printer
```
