# Regulated restrictive practices: definitions, reporting, example phrasings

Retrieved 2026-10-13. Every quoted passage below was checked against the source named under it. The example phrasings in sections 4 and 5 are synthetic test data I wrote. They are not official text.

## 1. The five regulated restrictive practices (official definitions)

Source: *National Disability Insurance Scheme (Restrictive Practices and Behaviour Support) Rules 2018*, s 6 "Rules apply only to specified kinds of restrictive practices". Latest compilation: Compilation No. 1, F2020C01087, compiled 1 December 2020. The Federal Register of Legislation shows this as the in-force version. URL: https://www.legislation.gov.au/F2018L00632/latest/text (text at https://www.legislation.gov.au/F2018L00632/2020-12-01/2020-12-01/text/original/epub/OEBPS/document_1/document_1.html)

Lead-in: "A restrictive practice is a regulated restrictive practice if it is or involves any of the following:"

| Type | Official definition (verbatim, s 6) |
|---|---|
| Seclusion (s 6(a)) | "seclusion, which is the sole confinement of a person with disability in a room or a physical space at any hour of the day or night where voluntary exit is prevented, or not facilitated, or it is implied that voluntary exit is not permitted;" |
| Chemical restraint (s 6(b)) | "chemical restraint, which is the use of medication or chemical substance for the primary purpose of influencing a person's behaviour. It does not include the use of medication prescribed by a medical practitioner for the treatment of, or to enable treatment of, a diagnosed mental disorder, a physical illness or a physical condition;" |
| Mechanical restraint (s 6(c)) | "mechanical restraint, which is the use of a device to prevent, restrict, or subdue a person's movement for the primary purpose of influencing a person's behaviour but does not include the use of devices for therapeutic or non-behavioural purposes;" |
| Physical restraint (s 6(d)) | "physical restraint, which is the use or action of physical force to prevent, restrict or subdue movement of a person's body, or part of their body, for the primary purpose of influencing their behaviour. Physical restraint does not include the use of a hands-on technique in a reflexive way to guide or redirect a person away from potential harm/injury, consistent with what could reasonably be considered the exercise of care towards a person." |
| Environmental restraint (s 6(e)) | "environmental restraint, which restrict a person's free access to all parts of their environment, including items or activities." |

The note to s 6 says: "For the definition of restrictive practice, see section 9 of the Act. Only regulated restrictive practices are covered by this instrument." I did not fetch the s 9 wording of the NDIS Act for this file.

Implications for a flagging tool, read from the definitions above:
- The chemical, mechanical and physical definitions all turn on "primary purpose of influencing ... behaviour".
- Chemical restraint carves out medication prescribed for a diagnosed mental disorder, physical illness or physical condition.
- Mechanical restraint carves out devices used for "therapeutic or non-behavioural purposes".
- Physical restraint carves out reflexive hands-on guiding away from harm.

So, for example, bed rails or a lap belt can fall on either side depending on purpose. A tool should flag these for review and not auto-classify them.

## 2. Reportable-incident timeframes for unauthorised use

### 2a. What counts as reportable

Source: *NDIS (Incident Management and Reportable Incidents) Rules 2018* (F2018L00633, as made 18 May 2018). The Register lists no compilations, so this is the in-force version. URL: https://www.legislation.gov.au/F2018L00633/latest/text (text at https://www.legislation.gov.au/F2018L00633/asmade/2018-05-18/text/original/epub/OEBPS/document_1/document_1.html)

- s 16, Note 1, quoting NDIS Act s 73Z(4)(f): a reportable incident includes "the use of a restrictive practice in relation to a person with disability, other than where the use is in accordance with an authorisation (however described) of a State or Territory in relation to the person."
- s 16(3): "the use of a restrictive practice in relation to a person with disability where the use is in accordance with an authorisation (however described) of a State or Territory is a reportable incident if the use is not in accordance with a behaviour support plan for the person with disability."
- s 17: "A reference in this Part to a reportable incident that has occurred includes a reference to a reportable incident that is alleged to have occurred."

### 2b. Timeframes: which applies when

- **24 hours (Rules s 20).** This applies to death, serious injury, abuse or neglect, unlawful sexual or physical contact or assault, and sexual misconduct (s 20(1)(b)(i)-(v)). Unauthorised restrictive practice is not on this list. s 20(2): "the registered NDIS provider must notify the Commissioner of the following information within 24 hours".
- **5 business days (Rules s 21).** This covers every other reportable incident, which includes unauthorised restrictive practice. s 21(1)(b): "the reportable incident is not of a kind covered by paragraph 20(1)(b)". s 21(2)(b): "be given within 5 business days after the provider became aware that the reportable incident occurred".
- **NDIS Commission operational guidance.** Source: https://www.ndiscommission.gov.au/rules-and-standards/reportable-incidents-and-incident-management/reportable-incidents
  - The timeframes table says: "Use of a restrictive practice that is unauthorised by your state or territory, or does not follow a behaviour support plan for the person with disability." → "5 business days"
  - It adds: "If the incident has resulted in harm to a person with disability, it must be reported within 24 hours."
  - "Timeframes are calculated from when a registered NDIS provider became aware of the incident"
  - On the 5-day report: "This is the only form needed for incidents involving unauthorised use of a restrictive practice that has not caused immediate harm to a person with disability."
  - Portal note: "Two portals from 12 October 2026". All new incidents go into the new NDIS Commission Portal.

Summary for code:
- Unauthorised restrictive practice with no harm → 5 business days.
- Unauthorised restrictive practice that resulted in harm → 24 hours. In the Rules, harm generally brings the incident into a s 20 category, such as serious injury or abuse.
- In both cases the clock starts when the registered provider became aware.

### 2c. Routine reporting of authorised use

RP Rules s 14(1)(a): "the provider must give monthly reports to the Commissioner regarding the use of regulated restrictive practices by the provider". Under a short-term state approval, s 14(1)(b) requires a report "every 2 weeks while the approval is in force".

## 3. Who has the obligation, and what an unregistered sole trader should do

**Registered providers.** Incident Rules ss 20-21 put the duty to notify on "the registered NDIS provider". s 19 requires a person employed or engaged by a registered provider who becomes aware of a reportable incident to notify key personnel or a supervisor "as soon as possible". The RP Rules Part 2 conditions, including monthly reporting, are "conditions relating to the use of regulated restrictive practices that apply to all registered NDIS providers" (s 7(2)).

**Unregistered providers must not use regulated restrictive practices at all.**
- NDIS Commission, *Rules for implementing providers*: "It is a breach of the NDIS Rules for an unregistered provider to use regulated restrictive practices." Implementing providers "must be registered if they use regulated restrictive practices." Source: https://www.ndiscommission.gov.au/rules-and-standards/behaviour-support-and-restrictive-practices/rules-implementing-providers

**What an unregistered sole trader should do.** The NDIS Commission's behaviour support page lists "an unregistered NDIS provider is using restrictive practices" as something to report, and says "Report these to behavioursupport@ndiscommission.gov.au". For immediate risk: "If an NDIS Participant's life is at risk, or there's an immediate risk of harm or injury, please ring 000 (triple zero)." Source: https://www.ndiscommission.gov.au/rules-and-standards/behaviour-support-and-restrictive-practices

- The NDIS Code of Conduct applies to "unregistered NDIS providers, their key personnel and NDIS workers". It requires them to "Promptly take steps to raise and act on concerns about matters that might have an impact on the quality and safety of supports provided to people with disability." Source: https://www.ndiscommission.gov.au/rules-and-standards/ndis-code-conduct
- Non-emergency route: "If a person with disability could be injured or harmed soon but it's not an emergency, call the NDIS Commission as soon as possible. Call 1800 035 544". Source: https://www.ndiscommission.gov.au/complaints/make-complaint-about-provider-or-worker

Plain-language reading, which is my synthesis of the sources above:
- An unregistered sole trader has no s 20/21 notification duty, because that duty belongs to registered providers.
- They also may not use any regulated restrictive practice.
- If they used one, or saw another provider use one, they should stop if it is safe and record it. They should raise it with the NDIS Commission (behavioursupport@ndiscommission.gov.au or 1800 035 544), or call 000 if anyone is at immediate risk.
- No official source states a specific deadline for an unregistered provider's own report.

**Victoria-specific context.** Source: https://www.dffh.vic.gov.au/about-victorian-senior-practitioner
- For NDIS participants, the Victorian Senior Practitioner's responsibilities include "Authorising the use of regulated restrictive practices in NDIS behaviour support plans" and "Providing additional approval of seclusion, mechanical and physical restraints". It also has "special powers under section 27 of the Disability Act in respect of the use of restrictive practices and compulsory treatment by disability services and registered NDIS providers."
- So in Victoria, "authorised" means authorised through this Disability Act 2006 (Vic) process, by an Authorised Program Officer and/or the Senior Practitioner.

## 4. Synthetic phrasings a support worker might write (positives: possible regulated restrictive practice)

These are made-up test strings. Labels follow the s 6 definitions. Items marked (ambiguous) depend on purpose or authorisation and should be flagged for human review, not auto-classified.

### Seclusion
1. "Kept him in his room till he calmed down, door locked."
2. "Told her she couldn't come out of the bedroom until she settled."
3. "Put him in the sensory room and held the door shut for 10 mins."
4. "Locked the back gate so she had to stay in the yard by herself while she cooled off."
5. "Time out in the lounge on his own, I stood at the door so he couldn't leave."
6. "Left her in the car with the child locks on while I went into the shop."
7. "Closed him in the laundry when he started yelling."
8. "Shut the bedroom door and said he wasn't allowed out before dinner."
9. "She was confined to her unit for the afternoon after the incident."
10. "Put the latch on her door overnight so she wouldn't wander." (ambiguous: overnight safety vs behaviour; still sole confinement with exit prevented)

### Chemical restraint
1. "Gave him his PRN early to settle him before the outing."
2. "Gave her a Valium because she was getting worked up."
3. "Crushed the PRN into his juice so he'd calm down."
4. "Gave the extra quetiapine to help him settle, he was being difficult."
5. "Used her PRN lorazepam so she'd stop screaming."
6. "Doubled his evening meds so he'd sleep through and not get up."
7. "Gave Phenergan to make him drowsy before the bus trip."
8. "Mum said give her the calming tablet if she plays up, so I did."
9. "Gave PRN at 2pm even though the plan says only after strategies fail; she was agitated." (outside the plan, so unauthorised use)
10. "Gave her Seroquel to keep her quiet during the appointment."

### Mechanical restraint
1. "Put the bed rails up so he wouldn't get out at night." (ambiguous: a fall-prevention purpose would be excluded)
2. "Did up the lap belt on the wheelchair because he kept trying to stand and hit." (behavioural purpose)
3. "Put the mittens on her so she'd stop scratching at staff."
4. "Used the seatbelt buckle guard so he couldn't unclip in the car."
5. "Strapped her arms to the chair arms during the meltdown."
6. "Put the splints on so he couldn't hit himself." (ambiguous: therapeutic vs behavioural)
7. "Clipped his harness to the seat so he'd stay put on the bus."
8. "Tucked the sheets tight under the mattress so she couldn't climb out."
9. "Used the tray table on the wheelchair to stop him getting up during dinner."
10. "Zipped her into the bodysuit so she couldn't undress in public." (ambiguous: possibly mechanical or environmental depending on purpose)

### Physical restraint
1. "Held her wrists until she stopped hitting."
2. "Had to pin him down on the couch for a few minutes."
3. "Held his arms by his side so he couldn't lash out."
4. "Bear-hugged her from behind to stop her running at the other client."
5. "Sat on his legs till he stopped kicking."
6. "Held her head back so she couldn't bite."
7. "Pushed him into the chair and held his shoulders down."
8. "Two of us held him on the floor while he calmed down."
9. "Gripped her arm and marched her back inside when she refused."
10. "Held his hands together to stop him grabbing the food."

### Environmental restraint
1. "Locked the pantry so she couldn't get snacks."
2. "Took his phone away after he swore at me."
3. "Turned the wifi off so he'd stop gaming."
4. "Hid the TV remote till she finished her chores."
5. "Locked the fridge overnight."
6. "Put the knives and scissors in a locked drawer because of him." (ambiguous: environmental restraint if done to influence his behaviour)
7. "Removed the door handle from the inside of the front door."
8. "Not allowed to go to the shops this week as punishment."
9. "Kept his wallet so he couldn't buy cigarettes."
10. "Locked the bathroom so she couldn't flood it again."

## 5. Hard negatives: not a restrictive practice under the s 6 definitions

1. "Offered him a choice between going to the park or the library; he picked the library."
2. "Redirected her to the garden when she got upset; she came willingly."
3. "He chose to stay in his room and watch TV; door open, he came out for dinner."
4. "Gave her regular Webster-pack meds as prescribed by the GP for epilepsy."
5. "Gave Panadol for headache as per the doctor's instructions."
6. "Helped him put his seatbelt on for the drive; he can undo it himself."
7. "Gently took her elbow to guide her away from the hot stove." (reflexive guiding away from harm; excluded under s 6(d))
8. "Wheelchair brakes on while transferring her to the bed." (therapeutic or safety use, not behavioural; excluded under s 6(c))
9. "She asked me to hold onto her phone while she swam; gave it back after."
10. "Suggested a break when he got frustrated; he went for a walk on his own."

**Not a hard negative: authorised regulated restrictive practice.** "Gave PRN as per her authorised behaviour support plan" is still a regulated restrictive practice (chemical restraint, if its primary purpose is to influence behaviour). It is simply authorised. Authorised use in line with the behaviour support plan is not a reportable incident (Incident Rules s 16(1) Note 1 and s 16(3)), but registered providers must still include it in monthly reporting (RP Rules s 14). An unregistered provider may not use it at all (NDIS Commission implementing-provider page). The tool should label it "regulated restrictive practice, authorised" rather than "not a restrictive practice".
