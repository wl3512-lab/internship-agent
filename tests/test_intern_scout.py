"""The scout's judgement calls, which are the parts that can be quietly wrong.

A broken fetch announces itself. A location classifier that reads the
marketing body instead of the location field does not - it just quietly files
a job in London as remote, and she finds out by opening it.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401  (a made-up user in a temp folder; must load first)

import datetime as dt
import intern_mail as mail
import intern_apply as apply_mod
import intern_agent as agent
import intern_describe
import intern_odds as odds
import intern_report as report
import cover_model
import intern_tailor as tailor
import resume_model
import resume_tailor as tailor_resume
import intern_scout as scout
import internships


class TestLocation(unittest.TestCase):
    def test_location_field_decides(self):
        cases = {
            "Vancouver, BC": "vancouver",
            "Burnaby, British Columbia": "vancouver",
            "Toronto, Ontario": "canada",
            "Remote - Canada": "canada",
            "Remote (US)": "remote_us",
            "New York, NY": "us",
            "Remote": "remote_global",
            "London, United Kingdom": "other",
            "Berlin, Germany": "other",
        }
        for loc, want in cases.items():
            self.assertEqual(scout.classify_location(loc), want, loc)

    def test_body_never_overrides_a_stated_location(self):
        # the bug this exists for: a London job filed as remote because the
        # description mentions the company is remote-friendly
        body = "We are a remote-first company with offices across Canada and the US."
        self.assertEqual(scout.classify_location("London, United Kingdom", body), "other")
        self.assertEqual(scout.classify_location("Vancouver, BC", body), "vancouver")

    def test_body_used_only_when_there_is_no_location(self):
        self.assertEqual(scout.classify_location("", "Fully remote across Canada."), "canada")

    def test_join_us_is_not_the_united_states(self):
        # "us" is unusable in prose, so the loose pattern must stay off the body
        self.assertEqual(scout.classify_location("", "We would love for you to join us."), "other")


class TestFilter(unittest.TestCase):
    def test_internship_titles(self):
        for good in ["Software Engineer Intern", "AI Automation Co-op (Fall 2026)",
                     "Design Internship", "Student Researcher", "Engineering Co-Op"]:
            self.assertTrue(scout.is_internship(good), good)

    def test_graduate_roles_are_not_internships(self):
        for bad in ["Junior Designer", "Entry Level Engineer", "Senior ML Engineer",
                    "Internal Communications Manager", "International Sales Lead"]:
            self.assertFalse(scout.is_internship(bad), bad)

    def test_title_outweighs_body(self):
        # nearly every posting mentions ML somewhere; only a title makes it an AI role
        strong = scout.match_interests("Machine Learning Intern", "", {"ai"})
        weak = scout.match_interests("Warehouse Intern", "we use machine learning", {"ai"})
        self.assertEqual(strong, [("ai", 2)])
        self.assertEqual(weak, [("ai", 1)])

    def test_only_her_fields_match(self):
        self.assertEqual(scout.match_interests("Design Intern", "", {"ai"}), [])

    def test_words_inside_other_words_do_not_count(self):
        # "opportunity" is not Unity, "promotion" is not motion, "studios" is not iOS
        body = ("the opportunity to join a strong community; promotion "
                "materials for our studios and a deluxe lab")
        self.assertEqual(scout.match_interests("Laboratory Operations Intern", body,
                                               {"creative", "design", "software"}), [])

    def test_stems_still_reach_longer_words(self):
        self.assertEqual(scout.match_interests("Creative Technologist Intern", "", {"creative"}),
                         [("creative", 2)])
        self.assertEqual(scout.match_interests("Intern", "rapid prototyping in Figma", {"design"}),
                         [("design", 1)])


class TestScore(unittest.TestCase):
    def test_vancouver_ai_role_tops_out(self):
        n, why = scout.score(None, [("ai", 2)], "vancouver")
        self.assertEqual(n, 5)
        self.assertEqual(why, "An AI role, in Vancouver.")

    def test_us_role_scores_below_an_identical_canadian_one(self):
        ca, _ = scout.score(None, [("software", 2)], "canada")
        us, why = scout.score(None, [("software", 2)], "us")
        self.assertGreater(ca, us)
        self.assertIn("US-based", why)

    def test_reason_is_a_sentence(self):
        _, why = scout.score(None, [("design", 2)], "vancouver")
        self.assertTrue(why[0].isupper() and why.endswith("."), why)


class TestEligibility(unittest.TestCase):
    def _posting(self, body="", location="Vancouver, BC", grad_year="2029"):
        raw = {"src_id": "x", "role": "Design Intern", "company": "C", "url": "https://e.com",
               "location": location, "body": body}
        return scout.to_posting(raw, {"design"}, set(), grad_year)

    def test_citizenship_requirement_is_a_disqualification_not_a_flag(self):
        p = self._posting("Applicants must be a U.S. citizen with an active security clearance.")
        self.assertIn("not eligible", p["eligibility_note"])

    def test_us_roles_carry_no_warning_because_cpt_covers_them(self):
        # The test user is a Canadian citizen whose profile says US work needs no sponsorship, so a
        # US internship is ordinary. Warning about TN and H-1B on every US
        # posting was wrong, and it flagged 29 of 52 rows - enough noise to
        # get the whole column ignored.
        p = self._posting(location="New York, NY")
        self.assertEqual(p["eligibility_note"], "")

    def test_outside_north_america_still_warns(self):
        p = self._posting(location="Berlin, Germany")
        self.assertIn("may need a visa", p["eligibility_note"])

    def test_wrong_graduation_year_is_said_out_loud(self):
        p = self._posting("Must be graduating between December 2026 and June 2027.")
        self.assertIn("2029", p["eligibility_note"])

    def test_citizenship_rule_outranks_a_year_mismatch(self):
        p = self._posting("Graduating in 2027. Must be a U.S. citizen with clearance.")
        self.assertIn("not eligible", p["eligibility_note"])
        self.assertNotIn("2027", p["eligibility_note"])

    def test_canadian_roles_carry_no_warning(self):
        self.assertEqual(self._posting()["eligibility_note"], "")

    def test_only_https_survives(self):
        raw = {"src_id": "x", "role": "Design Intern", "company": "C",
               "url": "javascript:alert(1)", "location": "Vancouver, BC", "body": ""}
        p = scout.to_posting(raw, {"design"}, set())
        self.assertEqual(p["url"], "")
        self.assertEqual(p["apply_url"], "")


class TestStore(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_rerun_does_not_resurrect_a_decision(self):
        internships.apply({"postings": [{"id": "p1", "role": "R", "status": "skipped"}]}, self.path)
        # what a second scout run sends for a posting it already knows
        internships.apply({"postings": [{"id": "p1", "role": "R (updated)", "fit": 4}]}, self.path)
        row = internships.load(self.path)["postings"][0]
        self.assertEqual(row["status"], "skipped")
        self.assertEqual(row["role"], "R (updated)")

    def test_a_write_never_replaces_the_document(self):
        internships.apply({"postings": [{"id": "p1", "role": "R"}],
                           "notes": [{"id": "n1", "text": "keep me"}]}, self.path)
        internships.apply({"postings": [{"id": "p2", "role": "S"}]}, self.path)
        data = internships.load(self.path)
        self.assertEqual(len(data["postings"]), 2)
        self.assertEqual(len(data["notes"]), 1)

    def test_rows_without_an_id_are_dropped(self):
        internships.apply({"postings": [{"role": "no id"}]}, self.path)
        self.assertEqual(internships.load(self.path)["postings"], [])

    def test_deletion_must_be_explicit(self):
        internships.apply({"notes": [{"id": "n1", "text": "t"}]}, self.path)
        internships.apply({"postings": []}, self.path)          # omission is not removal
        self.assertEqual(len(internships.load(self.path)["notes"]), 1)
        internships.apply({"delete": {"notes": ["n1"]}}, self.path)
        self.assertEqual(internships.load(self.path)["notes"], [])


class TestMailParsing(unittest.TestCase):
    """Handshake's subject lines are the API here, so they get pinned down."""

    WHEN = "2026-09-20T12:00:00+00:00"
    BODY = ("New job match\n\nA new role at Magnet Media matches your preferences.\n\n"
            "Magnet Media\nDesign Intern\n\nInternship • New York City, NY (Hybrid)\n")

    def parse(self, subject, body="", sender="Handshake <x@notifications.joinhandshake.com>"):
        return mail.parse_message(subject, sender, body, "", self.WHEN)

    def test_job_match_subject(self):
        row = self.parse("New Design Intern at Magnet Media", self.BODY)
        self.assertEqual(row["role"], "Design Intern")
        self.assertEqual(row["company"], "Magnet Media")
        self.assertEqual(row["location"], "New York City, NY (Hybrid)")
        self.assertEqual(row["term"], "Internship")

    def test_first_job_alert_subject(self):
        row = self.parse('"Your first job alert": Earth Celebrations Inc. - VIDEO EDITING Internship')
        self.assertEqual(row["company"], "Earth Celebrations Inc")
        self.assertEqual(row["role"], "VIDEO EDITING Internship")

    def test_saved_job_is_marked_as_hers(self):
        row = self.parse("Still interested in this Events and Digital Media Design Assistant role?")
        self.assertTrue(row["saved_by_her"])

    def test_application_confirmation_records_a_submission(self):
        row = self.parse("Application sent to Zyyo — here's what's next")
        self.assertEqual(row["company"], "Zyyo")
        self.assertEqual(row["status"], "submitted")
        # the mail never names the role, and the record says so rather than guessing
        self.assertIn("doesn't name the role", row["fit_reasons"])

    def test_events_and_newsletters_are_not_jobs(self):
        for noise in ["New on Handshake: the fastest way to build AI skills",
                      "Reminder: Upcoming Appointment",
                      "Morgan Stanley is coming to Northgate",
                      "Sam, Northgate University On Campus sees you as a top applicant for X",
                      "You're registered for L'Oreal Coffee Chats",
                      "Wasserman Weekly Career Updates for Undergraduates - 9/21",
                      "See who's noticed you this week"]:
            self.assertIsNone(self.parse(noise), noise)

    def test_the_same_job_twice_is_one_row(self):
        a = self.parse("New Design Intern at Magnet Media", self.BODY)
        b = self.parse("New Design Intern at Magnet Media", self.BODY)
        self.assertEqual(a["id"], b["id"])

    def test_proofpoint_wrapper_comes_off(self):
        wrapped = ("https://urldefense.proofpoint.com/v2/url?u=https-3A__app.joinhandshake.com"
                   "_jobs_12345&d=DwMFaQ")
        self.assertEqual(mail.unwrap_proofpoint(wrapped),
                         "https://app.joinhandshake.com/jobs/12345")

    def test_an_ordinary_url_is_left_alone(self):
        plain = "https://app.joinhandshake.com/jobs/9"
        self.assertEqual(mail.unwrap_proofpoint(plain), plain)

    def test_no_location_claims_nothing(self):
        rows = mail.enrich([{"role": "Design Intern", "location": "", "from": "Handshake"}],
                                {"fields": ["design"]})
        self.assertEqual(rows[0]["location_group"], "unknown")
        self.assertEqual(rows[0].get("eligibility_note", ""), "")


class TestOdds(unittest.TestCase):
    """The shot assessment, whose failure mode is flattery.

    The first version grouped skills into thirteen broad areas her résumé
    covered entirely, so every posting scored 100% and the factor was
    decoration. That is the same failure her budget tracker had - a tool that
    tells you what you want to hear is worse than no tool.
    """

    PROFILE = {"resume_text": "Python, TypeScript, React, Next.js, Supabase, Figma, "
                              "p5.js, TouchDesigner, Arduino, WCAG accessibility audits, "
                              "user interviews, led a four-designer team for a client."}

    def setUp(self):
        self.hers = odds.her_vocabulary(self.PROFILE)

    def test_she_does_not_match_everything(self):
        # the flattery check: a real résumé must leave real gaps
        self.assertLess(len(self.hers), len(odds.SKILLS) * 0.6)
        self.assertIn("python", self.hers)
        self.assertNotIn("kubernetes", self.hers)

    def test_word_boundaries(self):
        self.assertFalse(odds._present("unity", "our citizen-developer community"))
        self.assertTrue(odds._present("unity", "shipped in Unity 2022"))
        self.assertFalse(odds._present("java", "JavaScript and TypeScript"))
        self.assertTrue(odds._present("java", "Java and Spring Boot"))
        self.assertFalse(odds._present("scala", "highly scalable systems"))

    def test_punctuated_names_survive(self):
        self.assertTrue(odds._present("c++", "C++ and Python"))
        self.assertTrue(odds._present("c#", "C# or similar"))
        self.assertTrue(odds._present("next.js", "built with Next.js"))

    def test_plurals_and_stems(self):
        self.assertTrue(odds._present("api", "works with APIs"))
        self.assertTrue(odds._present("prototyp", "rapid prototyping"))
        self.assertTrue(odds._present("document", "clear documentation"))

    def _p(self, **kw):
        base = {"id": "x", "fit": 4, "fit_reasons": "A design role, in Vancouver.",
                "status": "new", "requirements": "", "eligibility_note": "",
                "found_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        base.update(kw)
        return base

    def test_a_wall_is_a_wall(self):
        a = odds.assess(self._p(eligibility_note="Requires US citizenship - you are not eligible."),
                        self.PROFILE, self.hers)
        self.assertEqual(a["band"], "blocked")

    def test_cs_only_program_blocks_but_or_equivalent_does_not(self):
        hard = self._p(requirements="Currently enrolled in a Computer Science degree program.")
        soft = self._p(requirements="Enrolled in a Computer Science program, or equivalent "
                                    "practical experience. Python, Figma, user research.")
        self.assertEqual(odds.assess(hard, self.PROFILE, self.hers)["band"], "blocked")
        self.assertNotEqual(odds.assess(soft, self.PROFILE, self.hers)["band"], "blocked")

    def test_a_vague_posting_cannot_score_strong(self):
        # 1-of-1 used to read as a perfect match and put an IT helpdesk role
        # above a Cohere research internship
        vague = odds.assess(self._p(requirements="You know Python."), self.PROFILE, self.hers)
        self.assertNotEqual(vague["band"], "strong")

    def test_a_detailed_match_beats_a_detailed_miss(self):
        match = odds.assess(self._p(requirements="Python, React, Figma, user interviews, WCAG."),
                            self.PROFILE, self.hers)
        miss = odds.assess(self._p(requirements="Kubernetes, Terraform, Scala, Kafka, Redis."),
                           self.PROFILE, self.hers)
        self.assertGreater(match["score"], miss["score"])

    def test_every_factor_says_why(self):
        a = odds.assess(self._p(requirements="Python, React, Figma, Kubernetes, Scala."),
                        self.PROFILE, self.hers)
        for f in a["factors"]:
            self.assertTrue(f["says"].strip(), f)

    def test_it_addresses_her_not_about_her(self):
        a = odds.assess(self._p(requirements="Python, React, Figma."), self.PROFILE, self.hers)
        text = a["summary"] + " ".join(f["says"] for f in a["factors"])
        self.assertNotIn(" she ", text.lower())


class TestReport(unittest.TestCase):
    def test_it_builds_from_an_empty_tracker(self):
        path = tempfile.mktemp(suffix=".json")
        try:
            text = report.build(internships.load(path), path)
            self.assertIn("Internships", text)
            self.assertIn("Nothing sent yet", text)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_it_explains_how_the_shot_was_reached(self):
        path = tempfile.mktemp(suffix=".json")
        try:
            self.assertIn("heuristics", report.build(internships.load(path), path))
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestApplyGate(unittest.TestCase):
    """The fill plan, whose one job is to refuse when it should."""

    PROFILE = {"legal_first_name": "Samuel", "legal_name": "Samuel Rivera", "last_name": "Rivera",
               "preferred_first_name": "Sam", "grad_year": "2029", "email": "sam@northgate.example",
               "links": {"portfolio": "https://samrivera.example"}}

    def test_it_fills_what_it_honestly_knows(self):
        for label, want in [("First Name", "Samuel"), ("Last Name", "Rivera"),
                            ("Full Legal Name", "Samuel Rivera"),
                            ("Preferred First Name", "Sam"),
                            ("Email", "sam@northgate.example"),
                            ("Portfolio Link", "https://samrivera.example")]:
            self.assertEqual(apply_mod.answer_for(label, self.PROFILE, {}), want, label)

    def test_a_public_portfolio_password_is_blank_not_invented(self):
        self.assertEqual(apply_mod.answer_for("Portfolio Password", self.PROFILE, {}), "")

    def test_it_knows_when_it_does_not_know(self):
        self.assertIsNone(apply_mod.answer_for("What is your favourite typeface?",
                                               self.PROFILE, {}))

    def test_legal_declarations_are_recognised(self):
        for label in ["Are you legally authorized to work in the United States?",
                      "Will you now or in the future require sponsorship",
                      "Have you ever been convicted of a felony?",
                      "Voluntary Self-Identification of Disability"]:
            self.assertTrue(apply_mod.DECLARATION_RE.search(label), label)

    def test_an_ordinary_field_is_not_mistaken_for_one(self):
        for label in ["First Name", "Portfolio Link", "Expected graduation date",
                      "Why do you want to join?"]:
            self.assertFalse(apply_mod.DECLARATION_RE.search(label), label)

    def test_a_blocked_declaration_stops_the_whole_plan(self):
        plan = self._plan([
            {"label": "First Name", "required": True, "fields": [{"type": "input_text"}]},
            {"label": "Are you legally authorized to work in the United States?",
             "required": True, "fields": [{"type": "multi_value_single_select",
                                           "values": [{"label": "Yes"}, {"label": "No"}]}]},
        ])
        self.assertFalse(plan["ready_to_fill"])
        self.assertEqual(len(plan["needs_you"]), 1)

    def test_with_no_declarations_it_is_ready(self):
        plan = self._plan([
            {"label": "First Name", "required": True, "fields": [{"type": "input_text"}]},
            {"label": "Email", "required": True, "fields": [{"type": "input_text"}]},
        ])
        self.assertTrue(plan["ready_to_fill"])
        self.assertEqual(len(plan["filled"]), 2)

    def test_a_value_outside_the_offered_options_blocks(self):
        plan = self._plan([
            {"label": "Have you ever worked for Figma before?", "required": True,
             "fields": [{"type": "multi_value_single_select",
                         "values": [{"label": "Nope"}, {"label": "Yep"}]}]},
        ])
        # it answers "No", which is not on offer - that must block, not guess.
        # "No" is a substring of "Nope", so the fuzzy match has to refuse it.
        self.assertFalse(plan["ready_to_fill"])

    def test_a_sentence_option_still_matches_a_yes_or_no(self):
        # what real forms offer: "Yes, I am currently eligible to work in the
        # location where this role is based."
        opts = ["Yes, I am currently eligible to work in the location where this role is based.",
                "No, I am not currently eligible to work in the location where this role is based."]
        self.assertTrue(apply_mod.match_option("Yes", opts).startswith("Yes,"))
        self.assertTrue(apply_mod.match_option("No", opts).startswith("No,"))

    def test_short_answers_never_fuzzy_match(self):
        self.assertIsNone(apply_mod.match_option("No", ["Nope", "Yep"]))
        self.assertIsNone(apply_mod.match_option("Yes", ["Yesterday", "Tomorrow"]))

    def test_the_same_country_spelled_differently(self):
        for opts in (["Australia", "US", "UK"], ["Australia", "United States"],
                     ["USA", "Canada"]):
            self.assertIsNotNone(apply_mod.match_option("United States", opts), opts)

    def _plan(self, questions):
        path = tempfile.mktemp(suffix=".json")
        try:
            internships.apply({"postings": [{"id": "t1", "role": "R", "company": "C"}]}, path)
            real = apply_mod.board_questions
            apply_mod.board_questions = lambda p: questions
            try:
                loadp = apply_mod.load_profile
                apply_mod.load_profile = lambda: self.PROFILE
                return apply_mod.build_plan("t1", path)
            finally:
                apply_mod.board_questions = real
                apply_mod.load_profile = loadp
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestAsksFollowTheirPosting(unittest.TestCase):
    """A question about a posting she has ruled on is not a question.

    Four of the first sixteen were about Epic and Cohere roles already
    dropped. That is how a column meant to be short becomes one she stops
    reading, and she said so.
    """

    def setUp(self):
        self.path = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def _seed(self):
        internships.apply({
            "postings": [{"id": "p1", "role": "R", "company": "C", "status": "new"}],
            "asks": [{"id": "a1", "question": "Q?", "posting_id": "p1", "status": "open"}],
        }, self.path)

    def test_dropping_a_posting_closes_its_questions(self):
        self._seed()
        internships.apply({"postings": [{"id": "p1", "status": "skipped"}]}, self.path)
        ask = internships.load(self.path)["asks"][0]
        self.assertEqual(ask["status"], "answered")
        self.assertIn("dropped", ask["answer"])

    def test_a_live_posting_keeps_its_questions(self):
        self._seed()
        internships.apply({"postings": [{"id": "p1", "status": "ready"}]}, self.path)
        self.assertEqual(internships.load(self.path)["asks"][0]["status"], "open")

    def test_rejection_closes_them_too(self):
        self._seed()
        internships.apply({"postings": [{"id": "p1", "status": "rejected"}]}, self.path)
        self.assertEqual(internships.load(self.path)["asks"][0]["status"], "answered")

    def test_an_answer_she_gave_is_not_overwritten(self):
        self._seed()
        internships.apply({"asks": [{"id": "a1", "answer": "mine", "status": "answered"}]}, self.path)
        internships.apply({"postings": [{"id": "p1", "status": "skipped"}]}, self.path)
        self.assertEqual(internships.load(self.path)["asks"][0]["answer"], "mine")

    def test_questions_no_longer_carry_a_restated_reason(self):
        internships.apply({"postings": [{"id": "p9", "role": "R", "company": "C"}]}, self.path)
        tailor.save("p9", [], ["Did you do the thing?"], self.path)
        ask = internships.load(self.path)["asks"][0]
        self.assertNotIn("why", ask)


class TestResumeTailoring(unittest.TestCase):
    """Reorder, select, omit. Never rewrite, never invent."""

    def test_the_parse_loses_nothing(self):
        self.assertEqual(resume_model.check(), [])

    def test_it_finds_the_right_shape(self):
        r = resume_model.parse()
        self.assertEqual(len(r["experience"]), 3)
        self.assertEqual(len(r["projects"]), 4)
        self.assertIn("Design", r["skills"])

    def test_a_wrapped_sentence_is_not_a_new_entry(self):
        # "flaw unprompted. Rebuilt Jun-Sep 2026..." invented a fifth project
        titles = [e["title"] for e in resume_model.parse()["projects"]]
        self.assertTrue(all(len(t) < 90 for t in titles), titles)
        self.assertTrue(any("Tidepool" in t for t in titles))

    def test_skills_reorder_without_gaining_or_losing_any(self):
        skills = resume_model.parse()["skills"]
        out = tailor_resume.order_skills(skills, {"figma", "python"})
        for group, items in skills.items():
            self.assertEqual(sorted(out[group]["items"]), sorted(items), group)

    def test_named_tools_move_to_the_front(self):
        out = tailor_resume.order_skills({"Design": ["Adobe", "Figma", "Sketch"]}, {"figma"})
        self.assertEqual(out["Design"]["items"][0], "Figma")
        self.assertEqual(out["Design"]["lead"], 1)

    def test_dates_get_their_dash_back(self):
        self.assertEqual(tailor_resume.pretty_dates("Sep 2026 Present"), "Sep 2026 \u2013 Present")
        self.assertEqual(tailor_resume.pretty_dates("2023 2026"), "2023 \u2013 2026")

    def test_it_keeps_a_minimum_even_when_nothing_matches(self):
        path = tempfile.mktemp(suffix=".json")
        try:
            internships.apply({"postings": [{"id": "t", "role": "R", "company": "C",
                                             "requirements": "Fortran and COBOL only."}]}, path)
            plan, err = tailor_resume.build("t", path)
            self.assertIsNone(err)
            self.assertGreaterEqual(len(plan["projects"]), tailor_resume.KEEP_AT_LEAST)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_experience_stays_chronological(self):
        path = tempfile.mktemp(suffix=".json")
        try:
            internships.apply({"postings": [{"id": "t", "role": "R", "company": "C",
                                             "requirements": "Figma, design systems."}]}, path)
            plan, _ = tailor_resume.build("t", path)
            order = [r["entry"]["title"] for r in plan["experience"]]
            original = [e["title"] for e in resume_model.parse()["experience"]]
            self.assertEqual(order, original)
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestCoverLetter(unittest.TestCase):
    def test_her_letter_splits_into_its_five_jobs(self):
        roles = {b["role"] for b in cover_model.blocks()}
        for expected in ("hook", "cuts", "grind", "craft", "close"):
            self.assertIn(expected, roles)

    def test_every_sentence_is_one_she_wrote(self):
        path = tempfile.mktemp(suffix=".json")
        try:
            internships.apply({"postings": [{"id": "t", "role": "R", "company": "C",
                                             "requirements": "Figma.", "fields": ["design"]}]}, path)
            plan, _ = tailor_resume.build("t", path)
            letter = tailor_resume.cover_letter(plan)
            hers = " ".join(b["text"] for b in cover_model.blocks())
            body = [l for l in letter.splitlines()
                    if len(l) > 120 and not l.startswith(("#", "*", "[", "-"))]
            self.assertTrue(body)
            for para in body:
                self.assertIn(para[:70], hers)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_it_leaves_the_why_slot_rather_than_inventing_one(self):
        path = tempfile.mktemp(suffix=".json")
        try:
            internships.apply({"postings": [{"id": "t", "role": "R", "company": "Acme",
                                             "requirements": "Figma.", "fields": ["design"]}]}, path)
            plan, _ = tailor_resume.build("t", path)
            self.assertIn("WHY THIS ONE", tailor_resume.cover_letter(plan))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_it_signs_off_once(self):
        path = tempfile.mktemp(suffix=".json")
        try:
            internships.apply({"postings": [{"id": "t", "role": "R", "company": "C",
                                             "requirements": "Figma.", "fields": ["design"]}]}, path)
            plan, _ = tailor_resume.build("t", path)
            self.assertEqual(tailor_resume.cover_letter(plan).count("Sam Rivera"), 1)
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestHiddenGraduationWindow(unittest.TestCase):
    """The window is often only in the form, phrased as a question.

    Vercel and Scale AI both asked "do you expect to graduate between
    December 2027 and June 2028?", which neither description said. Both had
    already been ranked worth her evening and both had a tailored résumé
    written for them before anyone noticed.
    """

    def test_a_question_form_window_is_caught(self):
        self.assertIn("2029", scout.year_fit(
            "Do you expect to graduate between December 2027 and June 2028?", "2029"))

    def test_a_window_she_falls_inside_says_nothing(self):
        self.assertEqual(scout.year_fit(
            "Do you expect to graduate between December 2028 and June 2030?", "2029"), "")

    def test_the_statement_form_still_works(self):
        self.assertIn("2029", scout.year_fit(
            "Must be graduating between December 2026 and June 2027.", "2029"))

    def test_a_year_in_prose_is_not_a_window(self):
        self.assertEqual(scout.year_fit(
            "Founded in 2019, we ship to millions.", "2029"), "")


class TestTailoringIsActuallyPerJob(unittest.TestCase):
    """The point of tailoring is that two jobs get two different résumés.

    A generator that produces the same document every time still reports
    success, and reads as tailored until someone lines two of them up.
    """

    def _plan(self, requirements, role="Intern", fields=None):
        path = tempfile.mktemp(suffix=".json")
        try:
            internships.apply({"postings": [{"id": "t", "role": role, "company": "C",
                                             "requirements": requirements,
                                             "fields": fields or ["design"]}]}, path)
            plan, err = tailor_resume.build("t", path)
            self.assertIsNone(err)
            return plan
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_two_different_postings_keep_different_projects(self):
        design = self._plan("Figma, design systems, brand, typography.")
        engineering = self._plan("TypeScript, React, Supabase, testing, APIs.",
                                 role="Software Engineer Intern", fields=["software"])
        self.assertNotEqual([r["entry"]["title"] for r in design["projects"]],
                            [r["entry"]["title"] for r in engineering["projects"]])

    def test_the_skills_line_leads_with_what_they_asked_for(self):
        plan = self._plan("Figma and design systems.")
        self.assertEqual(plan["skills"]["Design"]["items"][0], "Figma")
        other = self._plan("TouchDesigner and Arduino.")
        self.assertNotEqual(other["skills"]["Design"]["items"][0], "Figma")

    def test_it_never_drops_below_the_floor(self):
        plan = self._plan("Fortran, COBOL, mainframe operations.")
        self.assertGreaterEqual(len(plan["projects"]), tailor_resume.KEEP_AT_LEAST)

    def test_it_never_goes_above_what_fits(self):
        plan = self._plan("Figma, design systems, prototyping, user research, Python, React.")
        self.assertLessEqual(len(plan["projects"]), tailor_resume.KEEP_AT_MOST)

    def test_the_summary_line_of_an_entry_stays_first(self):
        resume = resume_model.parse()
        original = {e["title"]: e["body"][0] for e in resume["projects"] if e["body"]}
        plan = self._plan("Figma, design systems, accessibility, prototyping.")
        for row in plan["projects"]:
            first = row["entry"]["body"][0]
            self.assertEqual(first, original[row["entry"]["title"]])

    def test_reordering_keeps_every_point(self):
        resume = resume_model.parse()
        original = {e["title"]: sorted(e["body"]) for e in resume["projects"]}
        plan = self._plan("Figma, accessibility, user research, prototyping.")
        for row in plan["projects"]:
            self.assertEqual(sorted(row["entry"]["body"]), original[row["entry"]["title"]])

    def test_the_tagline_keeps_all_its_facets(self):
        tag = resume_model.parse()["tagline"]
        out = tailor_resume.order_tagline(tag, {"react", "typescript"},
                                          {"role": "Software Engineer Intern"})
        self.assertEqual(sorted(f.strip() for f in out["text"].split("\u00b7")),
                         sorted(f.strip() for f in tag.split("\u00b7")))


class TestUploadsTheTailoredResume(unittest.TestCase):
    """An untailored upload is the failure here that looks completely fine.

    Right name, right person, right file type, and none of the work. The fill
    plan was pointing at her master PDF while the folder sat there with a
    tailored one in it, and that is the file that went onto Figma's form.
    """

    def test_it_never_falls_back_to_the_master_resume(self):
        master = apply_mod.load_profile().get("resume_source")
        got = apply_mod.answer_for("Resume/CV", apply_mod.load_profile(),
                                   {"id": "x", "role": "R", "company": "Nowhere"})
        self.assertNotEqual(got, master)
        self.assertEqual(got, "")

    def test_it_finds_the_tailored_one_when_it_exists(self):
        import intern_tailor
        posting = {"id": "t", "role": "Fake Role", "company": "Fake Co"}
        folder = intern_tailor.folder(posting)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "resume.pdf")
        try:
            with open(path, "w") as fh:
                fh.write("x")
            self.assertEqual(
                apply_mod.answer_for("Resume/CV", apply_mod.load_profile(), posting), path)
        finally:
            if os.path.exists(path):
                os.unlink(path)
            if os.path.isdir(folder) and not os.listdir(folder):
                os.rmdir(folder)

    def test_a_missing_tailored_resume_blocks_the_plan(self):
        path = tempfile.mktemp(suffix=".json")
        try:
            internships.apply({"postings": [{"id": "t2", "role": "R", "company": "Nowhere Co"}]}, path)
            real = apply_mod.board_questions
            apply_mod.board_questions = lambda p: [
                {"label": "Resume/CV", "required": True, "fields": [{"type": "input_file"}]}]
            try:
                plan = apply_mod.build_plan("t2", path)
            finally:
                apply_mod.board_questions = real
            self.assertFalse(plan["ready_to_fill"])
            self.assertIn("resume_tailor", plan["needs_you"][0]["why"])
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestCampusJobs(unittest.TestCase):
    """A job at her own university is not an internship.

    Scored as one it was buried: all 36 read as long shots because none of
    them are in Vancouver. There is no relocation and no visa question - F-1
    allows on-campus work without CPT - but there is a rule an internship does
    not have, which is that many are for graduate students only.
    """

    def _p(self, role, company="Northgate University On Campus", **kw):
        base = {"id": "x", "role": role, "company": company, "status": "new",
                "requirements": "", "eligibility_note": "", "fit": 2}
        base.update(kw)
        return base

    def test_it_recognises_a_campus_job(self):
        self.assertTrue(odds.is_campus(self._p("Visual Design Assistant")))
        self.assertFalse(odds.is_campus(self._p("Design Intern", "Figma")))
        # a campus abroad hires its own students
        self.assertFalse(odds.is_campus(self._p("Content Creator", "Northgate Doha On-Campus")))

    def test_graduate_only_roles_are_blocked(self):
        for role in ["Creative Technologist Graduate Assistant",
                     "ROSI Product Development Graduate Fellow",
                     "ISAW Digital Project Grad Assistant"]:
            a = odds.assess(self._p(role), None, set())
            self.assertEqual(a["band"], "blocked", role)
            self.assertIn("undergraduate", a["factors"][0]["says"])

    def test_design_work_on_campus_surfaces(self):
        for role in ["Visual Design Assistant", "Content Creator",
                     "UC Events Content Designer"]:
            self.assertIn(odds.assess(self._p(role), None, set())["band"],
                          ("strong", "real chance"), role)

    def test_grading_is_demoted_even_with_a_design_word_in_the_course(self):
        # "Wagner Grader: UPADM-GP 102 - Introduction to Social Policy"
        # matched "social" and read as design work
        a = odds.assess(self._p("Wagner Grader: UPADM-GP 102 \u2013 Introduction to Social Policy"),
                        None, set())
        self.assertEqual(a["band"], "long shot")

    def test_a_course_code_does_not_confuse_the_title(self):
        self.assertEqual(odds.role_head("Wagner Grader: UPADM-GP 102 \u2013 Intro"),
                         "Wagner Grader")
        self.assertEqual(odds.role_head("Visual Design Assistant"), "Visual Design Assistant")

    def test_campus_jobs_are_not_penalised_for_location(self):
        # the internship scorer would mark this "other" and warn about visas
        a = odds.assess(self._p("Visual Design Assistant"), None, set())
        self.assertNotIn("visa", " ".join(f["says"] for f in a["factors"]).lower()[:200]
                         .replace("no visa question", ""))


class TestOneSchoolManyCampuses(unittest.TestCase):
    """Campuses abroad post through the same job board.

    Treating the school name as "where the user already is" surfaced overseas campus
    jobs as if they were down the street, and ranked an overseas content
    role as her single best campus match.
    """

    def _p(self, company, role="Content Creator", **kw):
        base = {"id": "x", "role": role, "company": company, "status": "new",
                "requirements": "", "eligibility_note": "", "fit": 2, "location": ""}
        base.update(kw)
        return base

    def test_her_campus_counts(self):
        self.assertTrue(odds.is_campus(self._p("Northgate University On Campus")))
        self.assertFalse(odds.is_other_campus(self._p("Northgate University On Campus")))

    def test_the_other_campuses_do_not(self):
        for company in ["Northgate Doha On-Campus Student Employment",
                        "Northgate Singapore Visual Arts",
                        "Northgate University Doha"]:
            self.assertFalse(odds.is_campus(self._p(company)), company)
            self.assertTrue(odds.is_other_campus(self._p(company)), company)

    def test_an_overseas_campus_job_is_blocked_not_ranked(self):
        a = odds.assess(self._p("Northgate Doha On-Campus Student Employment"), None, set())
        self.assertEqual(a["band"], "blocked")
        self.assertIn("different campus", a["factors"][0]["says"])

    def test_the_location_field_is_read_too(self):
        # the company name alone does not always say which campus
        p = self._p("Northgate University On Campus", location="Singapore")
        self.assertTrue(odds.is_other_campus(p))

    def test_an_ordinary_employer_is_not_a_campus_job(self):
        self.assertFalse(odds.is_campus(self._p("Figma", "Brand Design Intern")))
        self.assertFalse(odds.is_other_campus(self._p("Figma", "Brand Design Intern")))


class TestDescriptionGap(unittest.TestCase):
    """Handshake gives a title and nothing else, and says so rather than
    pretending the résumé was tailored to a description."""

    def test_it_lists_what_has_no_description(self):
        rows = intern_describe.missing()
        self.assertTrue(all(not (r.get("requirements") or "").strip() for r in rows))

    def test_a_short_paste_is_refused(self):
        self.assertIn("error", intern_describe.describe("whatever", "too short"))

    def test_the_notes_admit_when_it_is_title_only(self):
        path = tempfile.mktemp(suffix=".json")
        try:
            internships.apply({"postings": [{"id": "t", "role": "Visual Design Assistant",
                                             "company": "C", "requirements": ""}]}, path)
            plan, _ = tailor_resume.build("t", path)
            self.assertEqual(plan["source"], "title only")
            self.assertIn("not its description", tailor_resume.render_notes(plan))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_a_real_description_is_used_when_there_is_one(self):
        path = tempfile.mktemp(suffix=".json")
        try:
            internships.apply({"postings": [{"id": "t", "role": "R", "company": "C",
                                             "requirements": "Figma, Adobe, design systems."}]}, path)
            plan, _ = tailor_resume.build("t", path)
            self.assertEqual(plan["source"], "description")
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestTheUnitedStatesIsBiggerThanTenCities(unittest.TestCase):
    """A city whitelist can never cover a country.

    Pittsburgh fell through it and was filed as "outside the US",
    which hung a visa warning on a job in Pennsylvania and dropped it below
    postings she is less suited to.
    """

    def test_cities_that_were_missing(self):
        for loc in ["Pittsburgh", "Cupertino", "Cary, NC", "Bellevue", "Brooklyn"]:
            self.assertEqual(scout.classify_location(loc), "us", loc)

    def test_states_spelled_out(self):
        for loc in ["Pennsylvania", "Somewhere, Ohio", "Remote - Oregon"]:
            self.assertIn(scout.classify_location(loc), ("us", "remote_us"), loc)

    def test_state_abbreviations_need_their_comma(self):
        self.assertEqual(scout.classify_location("Austin, TX"), "us")
        # "or" is a conjunction far more often than it is Oregon
        self.assertEqual(scout.classify_location("Dublin or Berlin"), "other")
        self.assertEqual(scout.classify_location("London or Paris"), "other")

    def test_canada_still_wins_over_a_shared_name(self):
        self.assertEqual(scout.classify_location("Vancouver, BC"), "vancouver")
        self.assertEqual(scout.classify_location("Toronto, Ontario"), "canada")

    def test_genuinely_elsewhere_is_still_elsewhere(self):
        for loc in ["London, United Kingdom", "Berlin, Germany", "Singapore"]:
            self.assertEqual(scout.classify_location(loc), "other", loc)


class TestAStatedGraduatingClassIsAWall(unittest.TestCase):
    """Four postings reached Ready that she is not eligible for.

    A stated graduating class is not a bar she can clear by writing a better
    letter, so treating it as a headwind put three Notion roles and a Scale AI
    one in front of her as things to apply to.
    """

    def _p(self, note):
        return {"id": "x", "eligibility_note": note}

    def test_a_stated_class_blocks(self):
        for note in ["Wants graduates of 2027 - you're 2029.",
                     "Wants graduates between 2027 and 2028 - you're 2029.",
                     "Wants graduates of 2027/2028 - you're 2029."]:
            self.assertTrue(agent.blocked(self._p(note)), note)

    def test_citizenship_and_degree_still_block(self):
        self.assertTrue(agent.blocked(self._p("Requires US citizenship - not eligible.")))
        self.assertTrue(agent.blocked(self._p("Asks for a PhD or master's.")))

    def test_rising_senior_stays_a_headwind(self):
        # a preference plenty of postings state without enforcing
        self.assertFalse(agent.blocked(
            self._p("Asks for a rising senior or final year - worth checking.")))

    def test_no_note_is_not_a_block(self):
        self.assertFalse(agent.blocked(self._p("")))
        self.assertFalse(agent.blocked({"id": "x"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
