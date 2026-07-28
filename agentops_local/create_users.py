import os, urllib.request, json
key = os.environ["SUPABASE_KEY"]
url = "http://supabase_kong_database:8000/auth/v1/admin/users"
for email in ["testuser2@local.dev", "testuser3@local.dev"]:
    body = json.dumps({"email":email,"password":"TestUser123!","email_confirm":True}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
    })
    try:
        r = urllib.request.urlopen(req, timeout=10)
        data = json.loads(r.read())
        print("  %s: id=%s" % (email, data["id"]))
    except urllib.error.HTTPError as e:
        print("  %s: HTTP %d (already exists)" % (email, e.code))
