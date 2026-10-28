# Initial owner account

The first owner account is created once when the app starts with
`PASKIBRA_OWNER_PASSWORD` set. Its username and display name are
`ItsSkellyHer3`, and its role is `Owner`.

On the server, add `PASKIBRA_OWNER_PASSWORD=<the requested password>` to
`~/paskibra_v2/.env`, restrict the file with `chmod 600`, then restart
`paskibra-v2.service`. The service reads this file during startup. The app
stores only a password hash; it does not reset an existing account's password
on later restarts. Remove the setting from `.env` after the account has been
created.

The deployment script deliberately keeps `.env` on the server and does not
upload local secrets.
