"""Build the council complaints test set (F2).

This is the single authoring source for the synthetic test set. Each entry
holds a letter and its labels. Labels are written with a *quote* (the exact
words in the letter) instead of character offsets, and this script finds
each quote to compute the span. That way no offset is ever typed by hand.

Output goes to two separate folders, so no step can see the answers:
    data/council_complaints/cases/case_XXX.json    -> Case      (given to steps)
    data/council_complaints/labels/case_XXX.json   -> CaseLabel (only the evaluator reads these)

All people, addresses, councils, phone numbers and reference numbers are invented.
Phone numbers use Ofcom's reserved drama range (07700 900xxx).

Run:  uv run python scripts/build_test_set.py
"""

import json
import sys
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schema import Case, CaseLabel, Citation, Issue, Span  # noqa: E402
from packs.council_complaints.categories import CATEGORIES  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "council_complaints"


def letter(text: str) -> str:
    """Tidy a triple-quoted letter: remove shared indentation and outer blank lines."""
    return dedent(text).strip()


# Each entry:
#   id, received, channel, style ("human" or "ai"), text, band
#   issues:    list of (summary, category, quote)
#   citations: list of (quote, normalised_ref, status)
#   notes:     why the band was chosen
ENTRIES = [
    # ------------------------------------------------------------------
    # Short, human-style letters
    # ------------------------------------------------------------------
    dict(
        id="case_001", received="2026-11-04", channel="email", style="human", band=4,
        text=letter("""
            hi, our boiler has been broken since the 2nd and nobody has come out. ive rang 4 times.
            its freezing at night and i have a 7 month old baby so we are using a little plug in heater
            which is costing a fortune. please can someone actually come.
            Jade Pemberton, 22 Orchard Rise, Harrowfield HF2 9LN
        """),
        issues=[("Boiler broken for days with no repair visit", "housing_repairs",
                 "our boiler has been broken since the 2nd and nobody has come out")],
        citations=[],
        notes="Band 4: no heating in cold weather with an infant in the home.",
    ),
    dict(
        id="case_002", received="2026-10-15", channel="web_form", style="human", band=2,
        text=letter("""
            Green bin missed AGAIN on Tuesday. Third time since September. The crew just skip our road
            (Fenwick Lane) because of the parked cars I think. Can you sort it please. - Martin Oduya
        """),
        issues=[("Green bin collection repeatedly missed", "waste_recycling",
                 "Green bin missed AGAIN on Tuesday. Third time since September.")],
        citations=[],
        notes="Band 2: repeated routine failure, no health or safety impact.",
    ),
    dict(
        id="case_003", received="2026-10-21", channel="letter", style="human", band=3,
        text=letter("""
            Dear Sir/Madam,

            There is a large pothole outside 9 Brackley Road which has been there since August. I reported
            it online (ref HW-55210) and nothing has happened. Last week my wife tripped on the edge of it
            and hurt her wrist. I understand the council has a duty under section 41 of the Highways Act 1980
            to maintain the road. Please repair it before someone is seriously hurt.

            Yours faithfully,
            Derek Ansell
        """),
        issues=[("Reported pothole not repaired and has caused a fall", "highways",
                 "There is a large pothole outside 9 Brackley Road which has been there since August.")],
        citations=[("section 41 of the Highways Act 1980", "Highways Act 1980, s.41", "verified")],
        notes="Band 3: ongoing hazard that has already caused an injury, but no immediate danger to life.",
    ),
    dict(
        id="case_004", received="2026-11-09", channel="phone", style="human", band=5,
        text=letter("""
            Call note. Caller says the bathroom ceiling in her flat has partly come down after a leak from
            the flat above. Water is still coming through near the light fitting and the electrics in the
            hall keep tripping. She is 78 and lives alone. Asked for someone today.
            Caller: Mrs Irene Folau, Flat 6, Marlow House, Kelsbridge KZ4 1RT.
        """),
        issues=[("Bathroom ceiling collapsed with water near electrics", "housing_repairs",
                 "the bathroom ceiling in her flat has partly come down after a leak from\nthe flat above")],
        citations=[],
        notes="Band 5: water near live electrics after a ceiling collapse, older resident living alone.",
    ),
    dict(
        id="case_005", received="2026-10-30", channel="email", style="human", band=1,
        text=letter("""
            Just a small thing but the opening times on the website for Wyncombe library still say open till
            8 on thursdays, it closed at 6 when I got there. Not the end of the world, maybe update the page?
            Thanks, Priya Lal
        """),
        issues=[("Library opening hours on website are wrong", "general_feedback",
                 "the opening times on the website for Wyncombe library still say open till\n8 on thursdays")],
        citations=[],
        notes="Band 1: minor website correction.",
    ),
    dict(
        id="case_006", received="2026-10-27", channel="web_form", style="human", band=3,
        text=letter("""
            My neighbour at no. 31 plays music really loud most nights until 3 or 4am. I've got work at 7.
            Ive kept a diary for 6 weeks and sent it in but no one has called me back. My friend said its a
            statutory nuisance under the Environmental Protection Act 1990 s79 so you have to look into it??
            Tom Brierley, 29 Calder Street
        """),
        issues=[
            ("Neighbour plays loud music late at night", "noise_asb",
             "My neighbour at no. 31 plays music really loud most nights until 3 or 4am."),
            ("Noise diary submitted but no call back", "complaint_handling",
             "Ive kept a diary for 6 weeks and sent it in but no one has called me back."),
        ],
        citations=[("Environmental Protection Act 1990 s79", "Environmental Protection Act 1990, s.79", "verified")],
        notes="Band 3: ongoing nuisance over weeks, no safety risk.",
    ),
    dict(
        id="case_007", received="2026-10-08", channel="letter", style="human", band=2,
        text=letter("""
            To Council Tax,

            I live on my own since my partner moved out in July but my bill still doesn't have the single
            person discount. I filled in the form twice. I think I'm entitled under section 11 of the Local
            Government Finance Act 1992. Please correct it and refund what I overpaid. Account 40918832.

            Sandra Whitlock
        """),
        issues=[("Single person discount not applied to council tax", "council_tax",
                 "my bill still doesn't have the single\nperson discount")],
        citations=[("section 11 of the Local\nGovernment Finance Act 1992", "Local Government Finance Act 1992, s.11", "verified")],
        notes="Band 2: billing error, no health or safety impact.",
    ),
    dict(
        id="case_008", received="2026-11-13", channel="email", style="human", band=5,
        text=letter("""
            I was told to leave my sisters flat today and I have nowhere to sleep tonight. I have my two boys
            with me (5 and 9). I went to the housing office this morning and they said come back Monday.
            I thought you had to give us somewhere under the Housing Act 1996 section 188 if we have kids??
            please help. Leanne Corrigan, phone 07700 900412
        """),
        issues=[
            ("Family with children homeless tonight", "homelessness",
             "I have nowhere to sleep tonight"),
            ("Turned away at housing office and told to return Monday", "staff_conduct",
             "I went to the housing office this morning and they said come back Monday."),
        ],
        citations=[("Housing Act 1996 section 188", "Housing Act 1996, s.188", "verified")],
        notes="Band 5: family with two children has nowhere to sleep tonight.",
    ),
    dict(
        id="case_009", received="2026-11-06", channel="web_form", style="human", band=2,
        text=letter("""
            I got a parking ticket on Elm Parade on 3 Nov but the bay sign was completely covered by a hedge,
            I've attached photos. Under the Council Accountability Act 2019 you have to cancel tickets where
            signs arent visible. Please cancel PCN KZ20471196. Ahmed Rahimi
        """),
        issues=[("Parking ticket issued where bay sign was hidden by a hedge", "parking",
                 "the bay sign was completely covered by a hedge")],
        citations=[("Council Accountability Act 2019", "Council Accountability Act 2019", "not_found")],
        notes="Band 2: disputed ticket, no health or safety impact.",
    ),
    dict(
        id="case_019", received="2026-11-02", channel="email", style="human", band=1,
        text=letter("""
            hello, the bench in Mill Lane park has a broken slat, not dangerous just a bit wobbly. would be
            nice if it got fixed before spring. cheers, Gareth
        """),
        issues=[("Park bench has a broken slat", "parks_open_spaces",
                 "the bench in Mill Lane park has a broken slat")],
        citations=[],
        notes="Band 1: minor maintenance, writer says it is not dangerous.",
    ),
    # ------------------------------------------------------------------
    # Long, AI-style letters
    # ------------------------------------------------------------------
    dict(
        id="case_010", received="2026-10-19", channel="email", style="ai", band=4,
        text=letter("""
            Dear Housing Services Team,

            I am writing to formally raise a complaint regarding the persistent and worsening damp and mould
            in my property at 41 Thornbury Walk, Harrowfield HF1 4XP, which I rent from Harrowfield Borough
            Council.

            Since March 2026, black mould has spread across the bedroom walls and ceiling of the room my two
            children share. My younger son, who is four, has asthma, and his GP has advised in writing that
            the mould is likely to be making his symptoms worse. Despite three visits from your contractors,
            the only action taken has been to wipe the walls with a mould wash, which has not addressed the
            underlying cause.

            I would respectfully remind the Council of its obligations as a landlord. Under section 11 of the
            Landlord and Tenant Act 1985, the Council is required to keep the structure and exterior of the
            dwelling in repair. Furthermore, section 9A of the Landlord and Tenant Act 1985 requires that the
            property be fit for human habitation at the start of and throughout the tenancy. I also
            understand that the Residential Damp Prevention Act 2021 places a specific duty on social
            landlords to resolve reported mould within 28 days, and that section 48 of the Landlord and
            Tenant Act 1985 entitles tenants to a rent reduction while such works remain outstanding.

            In addition, I submitted a formal complaint about this matter on 14 August 2026 and have received
            no acknowledgement or response, which I understand falls well outside your published complaint
            handling timescales.

            I would therefore be grateful if the Council could:
            1. Arrange a full damp survey within the next seven days;
            2. Carry out the necessary remedial works without further delay;
            3. Provide a written response to my complaint of 14 August 2026.

            Thank you for your time and attention to this important matter. I look forward to your prompt
            response.

            Yours sincerely,
            Natalie Okonkwo-Reid
        """),
        issues=[
            ("Black mould in children's bedroom not fixed after three visits", "housing_repairs",
             "black mould has spread across the bedroom walls and ceiling of the room my two\nchildren share"),
            ("Formal complaint from August received no response", "complaint_handling",
             "I submitted a formal complaint about this matter on 14 August 2026 and have received\nno acknowledgement or response"),
        ],
        citations=[
            ("section 11 of the\nLandlord and Tenant Act 1985", "Landlord and Tenant Act 1985, s.11", "verified"),
            ("section 9A of the Landlord and Tenant Act 1985", "Landlord and Tenant Act 1985, s.9A", "verified"),
            ("Residential Damp Prevention Act 2021", "Residential Damp Prevention Act 2021", "not_found"),
            ("section 48 of the Landlord and\nTenant Act 1985", "Landlord and Tenant Act 1985, s.48", "needs_review"),
        ],
        notes="Band 4: mould is worsening a four-year-old's asthma, confirmed by a GP.",
    ),
    dict(
        id="case_011", received="2026-10-12", channel="letter", style="ai", band=3,
        text=letter("""
            Dear Sir or Madam,

            I am writing to raise a formal complaint about the withdrawal of my assisted bin collection and
            the Council's continued failure to communicate with me in an accessible way.

            I am a wheelchair user and have had an assisted collection at 3 Hollins Court, Eastmoor EQ7 2DW,
            for over five years. In September this service was withdrawn without notice. Since then my
            bins have not been emptied unless a neighbour moves them to the kerb for me, which is not always
            possible.

            I also have a hearing impairment and have asked on several occasions to be contacted by email
            rather than telephone. Despite this, every response I have received has been a voicemail
            asking me to call back, which I cannot do.

            I would like to draw your attention to section 20 of the Equality Act 2010, which requires the
            Council to make reasonable adjustments for disabled people. The Council is also bound by the
            public sector equality duty in section 149 of the Equality Act 2010. In addition, section 412
            of the Equality Act 2010 makes it unlawful to withdraw an established adjustment without a
            written assessment, and the Public Services Fairness Act 2016 requires councils to respond in
            the format a resident has requested.

            I would be grateful if the Council could reinstate my assisted collection, update my contact
            preferences to email only, and confirm both in writing.

            Yours faithfully,
            Colin Ashworth-Bayliss
        """),
        issues=[
            ("Assisted bin collection withdrawn without notice", "waste_recycling",
             "In September this service was withdrawn without notice."),
            ("Council keeps phoning a resident with a hearing impairment who asked for email", "equality_access",
             "every response I have received has been a voicemail\nasking me to call back, which I cannot do"),
        ],
        citations=[
            ("section 20 of the Equality Act 2010", "Equality Act 2010, s.20", "verified"),
            ("section 149 of the Equality Act 2010", "Equality Act 2010, s.149", "verified"),
            ("section 412\nof the Equality Act 2010", "Equality Act 2010, s.412", "needs_review"),
            ("Public Services Fairness Act 2016", "Public Services Fairness Act 2016", "not_found"),
        ],
        notes="Band 3: ongoing failure affecting a disabled resident, but no immediate danger.",
    ),
    dict(
        id="case_012", received="2026-11-11", channel="email", style="ai", band=4,
        text=letter("""
            Dear Adult Social Care Team,

            I am writing on behalf of my father, Mr Leonard Haskins, aged 84, of 17 Weir View, Kelsbridge
            KZ2 8HN, to express my serious concern about the delay in assessing his care needs.

            I first requested a needs assessment on 2 July 2026. More than four months later, no assessment
            has taken place. In that time my father has fallen at home twice, most recently on 6 November,
            when he lay on the kitchen floor for several hours before a neighbour found him. He lives alone
            and is becoming increasingly frail.

            When I telephoned to chase the referral, the social worker I spoke to was dismissive and told me
            that "everyone is waiting" and that I should "stop ringing". I found this deeply upsetting.

            I understand that section 9 of the Care Act 2014 requires the local authority to assess any
            adult who appears to need care and support. I also note that section 150 of the Care Act 2014
            sets a maximum waiting time of 28 days for such assessments, and that the Local Authority
            Response Times Act 2020 requires a written explanation for any delay beyond that period.
            Finally, under section 6 of the Human Rights Act 1998, the Council must act compatibly with my
            father's rights.

            I would ask that an assessment is arranged as a matter of urgency, and that my concerns about
            the conduct of the call are passed to the relevant manager.

            Kind regards,
            Rachel Haskins-Moore
        """),
        issues=[
            ("Care needs assessment delayed over four months for frail 84-year-old who has fallen", "adult_social_care",
             "More than four months later, no assessment\nhas taken place."),
            ("Social worker was dismissive on the phone", "staff_conduct",
             "the social worker I spoke to was dismissive"),
        ],
        citations=[
            ("section 9 of the Care Act 2014", "Care Act 2014, s.9", "verified"),
            ("section 150 of the Care Act 2014", "Care Act 2014, s.150", "needs_review"),
            ("Local Authority\nResponse Times Act 2020", "Local Authority Response Times Act 2020", "not_found"),
            ("section 6 of the Human Rights Act 1998", "Human Rights Act 1998, s.6", "verified"),
        ],
        notes="Band 4: older person living alone has already fallen twice while waiting.",
    ),
    dict(
        id="case_013", received="2026-10-23", channel="web_form", style="ai", band=2,
        text=letter("""
            Subject: Formal complaint regarding unanswered Freedom of Information request

            Dear Information Governance Officer,

            I am writing to formally complain that the Council has failed to respond to my Freedom of
            Information request submitted on 1 September 2026 (reference FOI-26-1187), which asked for the
            number of temporary accommodation placements made by the Council in each of the last three
            financial years.

            Under section 1 of the Freedom of Information Act 2000, I have a general right to be told
            whether the Council holds this information and, if so, to have it communicated to me. The
            statutory deadline for a response has now long passed. I would further note that section 94 of
            the Freedom of Information Act 2000 obliges a public authority to pay a fixed penalty to the
            requester for each week a response is overdue.

            I would be grateful if the Council could provide the requested information without further
            delay and confirm what steps it will take to prevent similar delays in future.

            Yours faithfully,
            Owen Prothero
        """),
        issues=[("FOI request not answered within the statutory deadline", "information_request",
                 "the Council has failed to respond to my Freedom of\nInformation request submitted on 1 September 2026")],
        citations=[
            ("section 1 of the Freedom of Information Act 2000", "Freedom of Information Act 2000, s.1", "verified"),
            ("section 94 of\nthe Freedom of Information Act 2000", "Freedom of Information Act 2000, s.94", "needs_review"),
        ],
        notes="Band 2: late information request, no health or safety impact.",
    ),
    dict(
        id="case_014", received="2026-10-28", channel="letter", style="ai", band=3,
        text=letter("""
            Dear Highways and Environment Department,

            I wish to bring to your attention two related issues on Castleford Row, Eastmoor, which I believe
            require the Council's prompt intervention.

            Firstly, the pavement between numbers 12 and 30 has several broken and lifted paving slabs. I
            have personally witnessed two people trip on this stretch in the last month, one of whom was an
            elderly gentleman using a walking stick. Under the Highways Act 1980, section 41, the Council has
            a duty to maintain highways maintainable at public expense. I would also highlight that section
            512 of the Highways Act 1980 requires repairs to reported trip hazards to be completed within 48
            hours, and that the Highways Pothole Compensation Act 2018 entitles injured pedestrians to
            automatic compensation.

            Secondly, the alleyway behind the same stretch has become a site for repeated fly-tipping, with
            mattresses, rubble and bags of household waste left for several weeks. Section 89 of the
            Environmental Protection Act 1990 places a duty on the Council to keep relevant land clear of
            litter and refuse.

            I trust the Council will treat these matters with the seriousness they deserve and I look forward
            to confirmation of the action to be taken.

            Yours faithfully,
            Margaret Ellingham
        """),
        issues=[
            ("Broken paving slabs causing trips", "highways",
             "the pavement between numbers 12 and 30 has several broken and lifted paving slabs"),
            ("Repeated fly-tipping in the alleyway", "street_cleansing",
             "the alleyway behind the same stretch has become a site for repeated fly-tipping"),
        ],
        citations=[
            ("Highways Act 1980, section 41", "Highways Act 1980, s.41", "verified"),
            ("section\n512 of the Highways Act 1980", "Highways Act 1980, s.512", "needs_review"),
            ("Highways Pothole Compensation Act 2018", "Highways Pothole Compensation Act 2018", "not_found"),
            ("Section 89 of the\nEnvironmental Protection Act 1990", "Environmental Protection Act 1990, s.89", "verified"),
        ],
        notes="Band 3: trip hazard has already caused falls; fly-tipping is ongoing. No immediate danger to life.",
    ),
    dict(
        id="case_015", received="2026-11-03", channel="email", style="ai", band=3,
        text=letter("""
            Dear Community Safety Team,

            I am writing to escalate my ongoing concerns about noise from my neighbour at 8 Ferris Gardens,
            Wyncombe WQ3 5JS, who has been running what appears to be a car repair business from his
            driveway since June.

            Most days, including weekends, there is loud hammering, power tools and revving engines from
            around 7am until late evening. I have reported this to the Council on three separate occasions,
            and each time the case has been closed without anyone contacting me or visiting the property.

            I believe this situation is likely to constitute a statutory nuisance under section 79 of the
            Environmental Protection Act 1990. As I have now made three reports, I would also like to
            request an anti-social behaviour case review, often called the Community Trigger, under section
            104 of the Anti-social Behaviour, Crime and Policing Act 2014. I further understand that
            section 181 of the Environmental Protection Act 1990 prohibits commercial vehicle repairs in
            residential areas, and that the Tenants' Bill of Rights Act 2022 guarantees residents a quiet
            home environment.

            I would appreciate a response confirming that a case review will take place and that an officer
            will visit.

            With thanks,
            Simon Achterberg
        """),
        issues=[
            ("Neighbour running noisy car repairs from driveway", "noise_asb",
             "loud hammering, power tools and revving engines"),
            ("Three noise reports closed without contact", "complaint_handling",
             "each time the case has been closed without anyone contacting me or visiting the property"),
        ],
        citations=[
            ("section 79 of the\nEnvironmental Protection Act 1990", "Environmental Protection Act 1990, s.79", "verified"),
            ("section\n104 of the Anti-social Behaviour, Crime and Policing Act 2014",
             "Anti-social Behaviour, Crime and Policing Act 2014, s.104", "verified"),
            ("section 181 of the Environmental Protection Act 1990", "Environmental Protection Act 1990, s.181", "needs_review"),
            ("Tenants' Bill of Rights Act 2022", "Tenants' Bill of Rights Act 2022", "not_found"),
        ],
        notes="Band 3: months of ongoing nuisance and repeated closed reports, no safety risk.",
    ),
    dict(
        id="case_016", received="2026-11-10", channel="letter", style="ai", band=4,
        text=letter("""
            Dear Housing Options Manager,

            I am writing to make a formal complaint about the temporary accommodation provided to my family
            and the lack of support we have received from Children's Services.

            My partner, our three children (aged 2, 6 and 11) and I were placed in a single room at the
            Station Lodge bed and breakfast in Harrowfield seven weeks ago. There are no cooking facilities,
            we share a bathroom with four other households, and my youngest child has had two chest
            infections since we arrived. I accept that the Council met its interim duty under section 188
            of the Housing Act 1996 by placing us here, but I am told that section 247 of the Housing Act
            1996 limits families with children to a maximum of six weeks in bed and breakfast
            accommodation.

            I have also asked our allocated housing officer to refer us for a children in need assessment
            under section 17 of the Children Act 1989, as my eldest has stopped attending school since the
            move. I have heard nothing back about this request.

            Lastly, I believe the way we have been treated may breach section 149 of the Equality Act 2012,
            as other families placed at the same time have already been moved.

            I would ask that we are moved to suitable self-contained accommodation as soon as possible, and
            that the children in need referral is made.

            Yours sincerely,
            Kerry-Ann Mbeki-Lowe
        """),
        issues=[
            ("Family with three children in unsuitable bed and breakfast for seven weeks", "homelessness",
             "were placed in a single room at the\nStation Lodge bed and breakfast in Harrowfield seven weeks ago"),
            ("Children in need referral not actioned", "children_services",
             "I have heard nothing back about this request."),
        ],
        citations=[
            ("section 188\nof the Housing Act 1996", "Housing Act 1996, s.188", "verified"),
            ("section 247 of the Housing Act\n1996", "Housing Act 1996, s.247", "needs_review"),
            ("section 17 of the Children Act 1989", "Children Act 1989, s.17", "verified"),
            ("section 149 of the Equality Act 2012", "Equality Act 2010, s.149 (cited as 2012)", "needs_review"),
        ],
        notes="Band 4: young child repeatedly ill in unsuitable accommodation, family has been there seven weeks.",
    ),
    dict(
        id="case_017", received="2026-10-16", channel="email", style="ai", band=3,
        text=letter("""
            Dear Revenues and Benefits Team,

            I am writing to formally complain about the handling of my council tax account (reference
            61200457) and the conduct of a member of staff.

            In August the Council removed my single person discount without explanation, even though I
            continue to live alone. When I disputed this, I was told the matter was "under review". Despite
            this, on 9 October I received a letter stating that my account had been passed to enforcement
            agents. I believe I was entitled to the discount under the Local Government Finance Act 1992
            (section 11), and it is unreasonable to pursue enforcement while a dispute is still open.

            When I called to query the enforcement letter, the call handler was rude, talked over me and
            ended the call while I was still speaking. I understand that the Local Authority Response Times
            Act 2020 requires councils to pause enforcement action while a complaint is under investigation.

            If this matter is not resolved, I intend to refer it to the Local Government and Social Care
            Ombudsman, whose remit to investigate is set out in section 26 of the Local Government Act 1974.

            Yours sincerely,
            Philippa Garside
        """),
        issues=[
            ("Account sent to enforcement agents while discount dispute is open", "council_tax",
             "my account had been passed to enforcement\nagents"),
            ("Call handler was rude and ended the call", "staff_conduct",
             "the call handler was rude, talked over me and\nended the call while I was still speaking"),
        ],
        citations=[
            ("Local Government Finance Act 1992\n(section 11)", "Local Government Finance Act 1992, s.11", "verified"),
            ("Local Authority Response Times\nAct 2020", "Local Authority Response Times Act 2020", "not_found"),
            ("section 26 of the Local Government Act 1974", "Local Government Act 1974, s.26", "verified"),
        ],
        notes="Band 3: enforcement action during an open dispute causes real harm, but no safety risk.",
    ),
    dict(
        id="case_018", received="2026-11-05", channel="web_form", style="ai", band=2,
        text=letter("""
            Dear Waste Services,

            I am writing to express my dissatisfaction with the repeated failure to collect the recycling
            from my address at 55 Pellow Crescent, Kelsbridge KZ6 3AF.

            My recycling bin has now been missed four weeks running. On each occasion I reported the missed
            collection through the Council's website and received an automated acknowledgement, but the bin
            was not collected on the following day as promised. Neighbouring properties appear to have had
            their bins emptied as normal.

            I would like to remind the Council that the Waste Collection Standards Act 2017 sets a legal
            maximum of two missed collections per household per year. I also note that section 89 of the
            Environmental Protection Act 1990 requires the Council to keep land clear of refuse, and that
            overflowing recycling is now spilling onto the pavement. Furthermore, the Council Accountability
            Act 2019 requires a named officer to respond personally to any repeat service failure.

            I would be grateful for confirmation of when the collection will be made and what will be done
            to prevent this from happening again.

            Yours faithfully,
            Diane Fairclough
        """),
        issues=[("Recycling bin missed four weeks running", "waste_recycling",
                 "My recycling bin has now been missed four weeks running.")],
        citations=[
            ("Waste Collection Standards Act 2017", "Waste Collection Standards Act 2017", "not_found"),
            ("section 89 of the\nEnvironmental Protection Act 1990", "Environmental Protection Act 1990, s.89", "verified"),
            ("Council Accountability\nAct 2019", "Council Accountability Act 2019", "not_found"),
        ],
        notes="Band 2: repeated missed collection, no health or safety impact.",
    ),
    dict(
        id="case_020", received="2026-11-12", channel="email", style="ai", band=1,
        text=letter("""
            Dear Customer Services,

            I am writing to express my profound dissatisfaction with the Council's online garden waste
            renewal form, which I found deeply frustrating and frankly unacceptable.

            On 10 November I attempted to renew my garden waste subscription online. On two occasions the
            form timed out after I had entered my details, and I was required to start again. I was
            eventually able to complete the renewal on my third attempt, but the experience was distressing
            and wasted around twenty minutes of my evening. I consider this an urgent matter of public
            service quality.

            I would remind the Council that under the Human Rights Act 1998, section 6, it must act
            compatibly with residents' rights, and that the Public Services Fairness Act 2016 requires all
            council websites to function without error.

            I would be grateful if the Council could review the form and extend the time-out period so that
            other residents do not have the same experience.

            Yours faithfully,
            Bernard Quilley
        """),
        issues=[("Online garden waste form timed out twice before renewal succeeded", "general_feedback",
                 "On two occasions the\nform timed out after I had entered my details")],
        citations=[
            ("Human Rights Act 1998, section 6", "Human Rights Act 1998, s.6", "verified"),
            ("Public Services Fairness Act 2016", "Public Services Fairness Act 2016", "not_found"),
        ],
        notes="Band 1: minor website problem, renewal succeeded. Strong words ('urgent', 'distressing') do not raise the band.",
    ),
]


def span_for(text: str, quote: str, case_id: str) -> Span:
    """Find the one place a quote appears in the text and return its span."""
    count = text.count(quote)
    if count != 1:
        raise ValueError(f"{case_id}: quote appears {count} times (must be exactly once): {quote!r}")
    start = text.index(quote)
    return Span(start=start, end=start + len(quote))


def build_entry(entry: dict) -> tuple[Case, CaseLabel]:
    text = entry["text"]
    case = Case(id=entry["id"], source_text=text, received_date=entry["received"], channel=entry["channel"])

    issues = []
    for summary, category, quote in entry["issues"]:
        if category not in CATEGORIES:
            raise ValueError(f"{entry['id']}: unknown category {category!r}")
        issues.append(Issue(summary=summary, category=category, span=span_for(text, quote, entry["id"])))

    citations = [
        Citation(raw_text=quote, normalised_ref=ref, status=status, span=span_for(text, quote, entry["id"]))
        for quote, ref, status in entry["citations"]
    ]

    label = CaseLabel(
        case_id=entry["id"],
        issues=issues,
        urgency_band=entry["band"],
        citations=citations,
        notes=f"style: {entry['style']}. {entry['notes']}",
    )
    return case, label


def write_json(path: Path, model) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ids = [e["id"] for e in ENTRIES]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")

    for entry in sorted(ENTRIES, key=lambda e: e["id"]):
        case, label = build_entry(entry)
        write_json(OUT_DIR / "cases" / f"{case.id}.json", case)
        write_json(OUT_DIR / "labels" / f"{case.id}.json", label)

    print(f"Wrote {len(ENTRIES)} cases and {len(ENTRIES)} labels to {OUT_DIR}")


if __name__ == "__main__":
    main()
