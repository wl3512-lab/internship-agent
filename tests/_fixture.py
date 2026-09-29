"""A made-up user for the tests, in a throwaway agent home.

Imported by every test module before any script, so config.py resolves every
path into a temporary folder and nothing ever reads or writes a real profile.
Sam Rivera does not exist; the résumé and letter are written in the layout the
parsers expect (see resume_model.py) - wrapped bullet lines included, because
text pulled out of a PDF wraps.
"""
import json
import os
import tempfile

HOME = tempfile.mkdtemp(prefix="internship-agent-test-")
os.environ["INTERNSHIP_AGENT_HOME"] = HOME

RESUME = """Sam Rivera
Product Designer · Creative Technologist · Design + Code
Vancouver, BC | sam@northgate.example | (555) 010-0000 | samrivera.example | linkedin.com/in/samrivera-example
EDUCATION
Northgate University, School of Design Expected May 2029
BFA, Interaction Design · Minor, Computer Science · Major GPA 3.80
EXPERIENCE
Design Lead Sep 2026 – Present
Northgate Design Studio, the student-run studio · Client: Harbor Health · Vancouver, BC
Lead a three-designer team on a semester-long client project, owning the brief and the weekly
client meetings.
Built a Figma component library of 40 components for the client's patient app, with every state
documented.
Resident Visual Artist May 2025 – Present
The Lantern Room · Vancouver, BC
Perform live audio-reactive visuals every Friday on a TouchDesigner network I built.
Barista and Social Media Lead Jun 2024 – Aug 2026
Common Grounds Cafe · Vancouver, BC
Shot and edited weekly Instagram reels in Premiere Pro; followers grew from 900 to 2,400 in a
year.
SELECTED PROJECTS
Tidepool  ·  Habit Tracker App · Solo Designer & Developer 2025 – 2026
Interviewed 8 students about why habit apps fail and turned it into 3 personas and 4 core flows.
Shipped a React and TypeScript PWA on Supabase with 30 components and 210 tests; its streak
system forgives one missed day. Rebuilt the onboarding in 2026 after testing with 6 new users.
TypeScript · React · Supabase · Testing · APIs
Lantern  ·  Museum Wayfinding Prototype · Interaction Design 2025
Designed an indoor wayfinding prototype in Figma with a small design system and tested it with 12
visitors; task time fell from 3 minutes to 70 seconds.
Figma · Design Systems · Prototyping · User Research · Accessibility
Signal Garden  ·  Sound Installation · Creative Coding 2024
Built a p5.js and Arduino installation where plants trigger sounds when touched; shown at the
spring student show.
p5.js · Arduino · Physical Computing · TouchDesigner
Rise Bakery Brand Kit  ·  Freelance Branding 2024
Designed a logo, typography system, packaging labels and a menu board; delivered print-ready
files in Illustrator.
Illustrator · Brand Identity · Typography · Print
SKILLS & TOOLS
Design  Adobe Creative Suite, Figma, TouchDesigner, prototyping, design systems, WCAG accessibility
Research  User interviews, usability testing, personas, journey mapping
Technical  Python, TypeScript, React, Next.js, Supabase, p5.js, Arduino, Git
Languages  English (Native), Spanish (Native)
"""

LETTER = """Sam Rivera
Vancouver, BC | sam@northgate.example
Dear Hiring Team,

When I tested Lantern with 12 museum visitors, the time it took them to find a room fell from three minutes to seventy seconds, and nobody asked me for help. That is the kind of result I want to keep designing for: a person gets where they are going without noticing the interface.

Most of what I know about product decisions comes from things I cut. In Tidepool I designed a public leaderboard, then removed it after interviews showed that ranking beginners made them quit sooner. I replaced it with a streak that forgives one missed day.

I'm also used to deadlines that don't move. I perform live visuals every Friday at The Lantern Room on a TouchDesigner network I built, and the set starts whether or not the patch is ready, so I test early and keep a backup running.

I also build what I design. I prototype in Figma and p5.js and ship small web apps in React and TypeScript, so people can try a working version before the design is settled.

My portfolio is at samrivera.example and my résumé is attached. I'd expect to learn a team's standards first and earn the right to question them. Could we set up twenty minutes to talk?

Best,
Sam Rivera
"""

RESUME_PDF = os.path.join(HOME, "Sam_Rivera_Resume.pdf")
with open(RESUME_PDF, "wb") as fh:
    fh.write(b"%PDF-1.4\n% placeholder for tests\n")

PROFILE = {
    "name": "Sam Rivera",
    "legal_first_name": "Samuel",
    "preferred_first_name": "Sam",
    "last_name": "Rivera",
    "legal_name": "Samuel Rivera",
    "email": "sam@northgate.example",
    "phone": "(555) 010-0000",
    "school": "Northgate University",
    "school_aliases": ["northgate", "northgate university"],
    "other_campuses": ["doha", "singapore"],
    "degree": "BFA, Interaction Design",
    "grad_year": "2029",
    "grad_term": "Spring",
    "city": "Vancouver",
    "country_of_residence": "Canada",
    "citizenship_country": "Canada",
    "work_authorization": {"canada": "citizen - no permit needed",
                           "us": "CPT available - no sponsorship needed"},
    "places": [
        {"group": "vancouver", "label": "Vancouver", "note": "in Vancouver",
         "match": ["vancouver", "burnaby", "richmond", "surrey", "victoria", "british columbia", "bc"]},
        {"group": "canada", "label": "Canada", "note": "in Canada, so no visa",
         "match": ["canada", "toronto", "montreal", "montréal", "ottawa", "calgary", "edmonton",
                   "waterloo", "halifax", "winnipeg", "quebec"]},
    ],
    "fields": ["creative", "design", "ai", "software"],
    "links": {"portfolio": "https://samrivera.example", "linkedin": "https://linkedin.com/in/samrivera-example"},
    "resume_text": RESUME,
    "resume_source": RESUME_PDF,
    "cover_letter_text": LETTER,
}

with open(os.path.join(HOME, "profile.json"), "w") as fh:
    json.dump(PROFILE, fh, indent=1)
