# JARVIS Reminders & Tasks

## Included
- Persistent reminders in the existing local SQLite database.
- Optional due date/time stored as an ISO-8601 timestamp; naive timestamps are interpreted in Europe/Madrid.
- Date validation rejects malformed due dates.
- Reminder centre in System Configuration with create, complete, and delete controls.
- Voice/chat commands: "remind me to call the bank in 15 minutes", "remind me to take out rubbish tomorrow at 5pm", "remind me to pay rent at 17:30", and "remind me to call mum tomorrow".
- "Show my reminders" lists active reminders.
- While the dashboard is open, it checks for due reminders every 15 seconds.
- Browser desktop notifications are opt-in. The user must select Enable Notifications and grant permission.
- In-dashboard notice is used even when desktop notification permission is unavailable or denied.

## Important operating limits
- The dashboard must remain open for browser-based due checks and notifications.
- This is not yet a Windows background service or an OS-level scheduled task. It does not promise alerts while JARVIS is closed or Windows is asleep.
- Notification permission is granted by the user in the browser; JARVIS never requests it without a click.
