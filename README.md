# Job Finder

A Python automation script that fetches job postings from selected company career pages, stores them in a JSON file, and sends an email notification if new jobs are found. Designed to run on a schedule (e.g., every hour) for continuous monitoring.

## Features

- Scrapes job postings from multiple pharma/biotech companies.
- Stores all job data in a local JSON file.
- Sends email alerts when new jobs are detected.
- Logs activity and errors for easy troubleshooting.
- Automatically manages log files, retaining logs for 4 weeks and deleting older ones.

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/Job-finder.git
cd Job-finder
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Email Credentials

- Create a file named `smtp_password.txt` in the project root directory.
- Paste your SMTP password inside (no quotes, just the password).
- Add `smtp_password.txt` to your `.gitignore` to keep it private.

### 4. Update Email Settings

Edit `jobscraper.py` and replace the following with your own email details:
- `from_email`
- `to_email`
- `smtp_username`

### 5. Run the Script

```bash
python jobscraper.py
```

### 6. (Optional) Schedule the Script

To run the script every hour, use a scheduler like `cron` (Linux/macOS):

```bash
crontab -e
```
Add this line to run every hour:
```
0 * * * * /usr/bin/python3 /path/to/Job-finder/jobscraper.py
```

## Notes

- The script creates/updates `jobs.json` with all job postings.
- All logs are saved in `jobscraper.log`.
- Log files are automatically rotated and retained for 4 weeks; older logs are deleted.
- Make sure your email provider allows SMTP access and "less secure apps" if needed.

## License

MIT License

