# Credits & Acknowledgments

ReceiptPi is built on the shoulders of amazing open-source projects. We thank all the creators and maintainers.

## Core Dependencies

### [ntfy.sh](https://ntfy.sh)
- **Purpose:** Lightweight pub-sub notification service
- **License:** Apache 2.0
- **URL:** https://github.com/binwiederhake/ntfy
- **Why:** Provides the message broker that powers print notifications

### [python-escpos](https://github.com/python-escpos/python-escpos)
- **Purpose:** Python library for ESC/POS thermal printers
- **License:** MIT
- **URL:** https://github.com/python-escpos/python-escpos
- **Why:** Core driver for communicating with USB thermal printers

### [Pillow (PIL)](https://pillow.readthedocs.io/)
- **Purpose:** Python Imaging Library for image processing
- **License:** HPND (Historical Permission Notice and Disclaimer)
- **URL:** https://github.com/python-pillow/Pillow
- **Why:** Handles image manipulation, conversion, and optimization for thermal printing

### [requests](https://requests.readthedocs.io/)
- **Purpose:** HTTP library for humans
- **License:** Apache 2.0
- **URL:** https://github.com/psf/requests
- **Why:** Makes HTTP requests to ntfy.sh and GitHub API simple and elegant

### [python-dotenv](https://github.com/theskumar/python-dotenv)
- **Purpose:** Loads environment variables from .env files
- **License:** BSD 3-Clause
- **URL:** https://github.com/theskumar/python-dotenv
- **Why:** Manages configuration without hardcoding secrets

### [pyusb](https://pyusb.github.io/pyusb/)
- **Purpose:** USB library for Python
- **License:** BSD 3-Clause (libusb-compatible)
- **URL:** https://github.com/pyusb/pyusb
- **Why:** Enables direct USB communication with thermal printers

### [psutil](https://psutil.readthedocs.io/)
- **Purpose:** Cross-platform library for retrieving system information
- **License:** BSD 3-Clause
- **URL:** https://github.com/giampaolo/psutil
- **Why:** Monitors system memory to prevent printer overload

### [qrcode](https://github.com/lincolnloop/python-qrcode)
- **Purpose:** QR code generation library
- **License:** BSD (3-Clause)
- **URL:** https://github.com/lincolnloop/python-qrcode
- **Why:** Generates QR codes from URLs and phone numbers for interactive receipts

### [pilmoji](https://github.com/jay3332/pilmoji)
- **Purpose:** Emoji rendering for PIL/Pillow
- **License:** MIT
- **URL:** https://github.com/jay3332/pilmoji
- **Why:** Renders emoji beautifully in printed messages

## Special Thanks

- **Orange Pi & DietPi Communities** - For providing lightweight hardware/OS platforms
- **GitHub** - For version control and release management
- **ntfy.sh** - For the public notification infrastructure
- **ESC/POS Community** - For reverse-engineering and documenting thermal printer protocols

## License

ReceiptPi is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

This means:
- ✅ Free to use, modify, and distribute
- ✅ Must share source code if you modify it
- ✅ Cannot be used for proprietary/commercial purposes without modification sharing
- ✅ Ensures improvements benefit everyone

See [LICENSE](LICENSE) for full details.

## Contributing

Want to help? We accept contributions! When you contribute:
1. Your code will be under the same AGPL-3.0 license
2. You're contributing to a free project for the community
3. Your name may be added to this credits list

---

**Made with ❤️ for the open-source community**
