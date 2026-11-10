# Cloud server

The data (about 21 GB) and the heavy analysis move to a free Oracle Cloud server.
The laptop keeps the code and the daily downloads from NSE, which often refuses
cloud servers, and sends new files up after each run.

## Files

| File | Runs on | Does |
|---|---|---|
| `setup_server.sh` | the server, once | security updates, logins by key only, swap, Python 3.14 with the pinned packages, Node 20 |
| `sync_up.sh` | the laptop | copies `data/`, `db/` and the website up; sends only what changed; refuses while the collector runs or a database is open |
| `verify_copy.py` | both | fingerprints every file (size and SHA-256) and counts every table's rows, then compares the two sides |

## First time

1. Create the server in the Oracle console (Ubuntu 24.04, VM.Standard.A1.Flex,
   Always Free sizes, 150 GB boot volume), with the public key
   `~/.ssh/micc_oracle_ed25519.pub`.
2. On the laptop, add the server to `~/.ssh/config`. The address stays out of
   this public repo:

   ```
   Host micc_server
     HostName <public IP>
     User ubuntu
     IdentityFile ~/.ssh/micc_oracle_ed25519
     IdentitiesOnly yes
   ```

3. Copy the setup script up and run it:
   `scp cloud/setup_server.sh micc_server: && ssh micc_server bash setup_server.sh`
4. Copy the data: `cloud/sync_up.sh`. The first run takes one to two hours.
5. Check the copy: write a manifest on each side with
   `verify_copy.py manifest data db -o <file>`, bring the server's back, and run
   `verify_copy.py compare`. It must print "the two copies match" before anything
   on the laptop is removed.

## Layout on the server

`~/micc/research` (this repo, with `data/` and `db/`) and `~/micc/website`.
