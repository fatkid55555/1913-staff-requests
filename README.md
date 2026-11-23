# Staff Requests — request off & shift trades

Employees scan the QR code next to the printed schedule, log in, and either
ask for days off or offer a shift to a coworker. Trades go to the coworker
first; once they accept (or for any day-off request) Joe gets an email and
approves or denies on the Manager screen.

## Files
- `app.py` — the whole website (Streamlit).
- `requirements.txt` — add-on tools the online host loads.
- `make_qr_code.py` — makes the printable QR sign (built once the site has its address).

## Where things live
- **Website:** Streamlit Community Cloud, deployed from this repo, main file
  `staff_requests/app.py`. (Address added here once live.)
- **Data:** an online Neon database — only names, usernames, scrambled
  passwords and requests. No restaurant data. The app creates its own tables
  the first time it starts.
- **Secrets** (Streamlit's secrets box, never in git): `DATABASE_URL`,
  `MANAGER_USERNAME`, `MANAGER_PASSWORD`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`,
  `ALERT_TO`, `APP_URL`.

## Logging in
- **Staff:** pick their name from the list, type the 4-digit code Joe gave them.
- **Joe:** tap "Manager login" at the bottom, real username + password.
- 5 wrong tries on one name locks it for 15 minutes. Codes are stored
  scrambled — they can't be looked up, only replaced.

## Everyday jobs (all on the Manager screen → Staff)
- **New hire:** type `Name, 1234` (or just the name for a random code), press
  Add, write down the code shown and give it to them.
- **Forgot code / locked out:** tap their name → type a new code → Save code.
  That also unlocks them.
- **Someone leaves:** tap their name → Turn off. They vanish from the name list;
  their history stays.

## Testing on the laptop
With no `DATABASE_URL` set, the app uses a throwaway test file in the Windows
temp folder and shows a yellow "TEST COPY" bar. Windows security on this laptop
blocks the online-database add-on (psycopg), so the laptop can only run the
test copy — the live site is unaffected.
