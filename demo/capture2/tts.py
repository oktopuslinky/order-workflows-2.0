#!/usr/bin/env python
"""Generate ElevenLabs voiceover clips for the demo, one mp3 per scene.
Key is read from $CLAUDE_JOB_DIR/tmp/eleven.env (never committed)."""
import json, os, sys, urllib.request, urllib.error, pathlib

HERE = pathlib.Path(__file__).resolve().parent
VO = (HERE / ".." / "video" / "public" / "vo").resolve()
VO.mkdir(parents=True, exist_ok=True)

# --- load key ---
env = pathlib.Path(os.environ["CLAUDE_JOB_DIR"]) / "tmp" / "eleven.env"
KEY = None
for line in env.read_text().splitlines():
    if line.startswith("ELEVENLABS_API_KEY="):
        KEY = line.split("=", 1)[1].strip()
assert KEY, "no key"

API = "https://api.elevenlabs.io"

def get(path):
    req = urllib.request.Request(API + path, headers={"xi-api-key": KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def pick_voice():
    try:
        vs = get("/v1/voices")["voices"]
    except Exception as e:
        print("voices fetch failed, using Adam id:", e)
        return "pNInz6obpgDQGcFmaJgB", "Adam(default)"
    # name field includes descriptors, e.g. "Charlie - Deep, Confident, Energetic"
    def find(sub):
        for v in vs:
            if sub in v["name"].lower():
                return v["voice_id"], v["name"]
        return None
    for want in ("charlie", "liam", "adam - dominant", "adam"):
        hit = find(want)
        if hit:
            return hit
    v = vs[0]
    return v["voice_id"], v["name"]

# Energetic startup narration, one segment per scene.
SEGMENTS = [
    ("intro",
     "Every team has workflows buried in documents. Orders, approvals, returns — "
     "described in prose that nobody can actually run. Workflow compiler turns that "
     "document into real, runnable Temporal code. Here's how."),
    ("login",
     "Sign in with a local account. No external services — your work stays on your machine."),
    ("create",
     "Start a project. Drop in a document — Word, PDF, Markdown, or just paste the text. "
     "Pick your model: hosted Nemotron in the cloud, or your own local G-P-U. Hit compile, "
     "and the pipeline goes to work — reading the document, discovering every workflow, and "
     "extracting the facts."),
    ("spec",
     "Out comes an editable spec for each workflow. Inputs, outputs, triggers, decisions — "
     "every one grounded in your document. Read it as a spec, preview it, or see it as a graph. "
     "This is the human gate. The model drafts; you stay in control."),
    ("edit",
     "Something off? Fix it right here. Answer the open questions, confirm the cross-workflow "
     "dependencies, edit any line. Then validate — and the compiler re-checks everything, "
     "reporting issues in plain language before a single line of code ships."),
    ("editrequest",
     "Bigger change? Just describe it. Write an edit request in plain English — add a fraud "
     "check, hold flagged orders for review — and the compiler translates it into precise spec "
     "edits, previews them, and logs every change."),
    ("results",
     "Approve, and the gate opens. Every workflow compiles to production Temporal code — "
     "activities, workers, starters, even tests. See the graph, the health score, the phase "
     "classification, then download the whole project as a zip, ready to run."),
    ("metrics",
     "And it tracks what it saved you. Measured pipeline time against a human team — real hours "
     "back on every single project."),
    ("config",
     "Make it yours. Flip to dark mode, tune the time-saved baselines to your team, set your "
     "page size. Save — and you're set."),
    ("docs",
     "And everything is documented, right in the app — the full spec grammar, and the "
     "edit-request format."),
    ("outro",
     "From a messy document to runnable code — with a human in the loop the whole way. "
     "That's workflow compiler."),
]

def synth(voice_id, name, text, out):
    body = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.34, "similarity_boost": 0.80,
            "style": 0.45, "use_speaker_boost": True,
        },
    }).encode()
    req = urllib.request.Request(
        f"{API}/v1/text-to-speech/{voice_id}",
        data=body,
        headers={"xi-api-key": KEY, "Content-Type": "application/json",
                 "Accept": "audio/mpeg"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    out.write_bytes(data)
    print(f"  {name} -> {out.name} ({len(data)//1024} KB)")

def main():
    vid, vname = pick_voice()
    print("voice:", vname, vid)
    for name, text in SEGMENTS:
        out = VO / f"{name}.mp3"
        try:
            synth(vid, name, text, out)
        except urllib.error.HTTPError as e:
            print("  HTTP", e.code, e.read()[:300].decode("utf-8", "replace"))
            sys.exit(1)
    print("VO DONE ->", VO)

if __name__ == "__main__":
    main()
