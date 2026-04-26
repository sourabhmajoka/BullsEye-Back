"""
fix_users.py — Run this ONCE to unblock all users stuck with is_verified=False.

Usage:
    pip install psycopg2-binary
    python fix_users.py

This script connects directly to your Render PostgreSQL database and:
1. Shows all users currently in the DB
2. Sets is_verified=True for every real user (anyone who isn't a guest)
   so they can log in immediately with their password
"""
import psycopg2

DATABASE_URL = (
    "postgresql://bullseye_db_xht3_user:By3C4ypgcvlec0q7QcSz0sAEzoSwjhZt"
    "@dpg-d7mrf1i8qa3s739sajl0-a.oregon-postgres.render.com/bullseye_db_xht3"
)

print("Connecting to Render PostgreSQL...")
conn = psycopg2.connect(DATABASE_URL)
cur  = conn.cursor()

# ── 1. Show all current users ────────────────────────────────────────────────
print("\n=== CURRENT USERS IN DATABASE ===")
cur.execute("""
    SELECT id, username, email, is_verified, is_guest, created_at
    FROM users
    ORDER BY id
""")
rows = cur.fetchall()
if not rows:
    print("  No users found.")
else:
    print(f"  {'ID':<5} {'Username':<20} {'Email':<35} {'Verified':<10} {'Guest':<8} {'Created'}")
    print(f"  {'-'*90}")
    for row in rows:
        id_, uname, email, verified, guest, created = row
        print(f"  {id_:<5} {uname:<20} {email:<35} {str(verified):<10} {str(guest):<8} {created}")

# ── 2. Fix all real (non-guest) users who are not yet verified ───────────────
cur.execute("""
    UPDATE users
    SET is_verified = TRUE
    WHERE is_guest = FALSE
      AND is_verified = FALSE
    RETURNING id, username, email
""")
fixed = cur.fetchall()
conn.commit()

if fixed:
    print(f"\n✅ Fixed {len(fixed)} user(s) — they can now log in:")
    for row in fixed:
        print(f"   ID={row[0]}  username={row[1]}  email={row[2]}")
else:
    print("\n✅ No stuck users found (all already verified).")

# ── 3. Confirm final state ───────────────────────────────────────────────────
print("\n=== FINAL STATE ===")
cur.execute("""
    SELECT id, username, email, is_verified, is_guest
    FROM users
    ORDER BY id
""")
for row in cur.fetchall():
    id_, uname, email, verified, guest = row
    status = "GUEST" if guest else ("✅ verified" if verified else "❌ BLOCKED")
    print(f"  ID={id_:<4} {uname:<20} {email:<35} → {status}")

cur.close()
conn.close()
print("\nDone. All blocked users are now unblocked.")
print("Next step: deploy the fixed backend to Render (see README in the zip).")