# Week 2 submit checklist (for you, the human)

Deadline: Sunday 18 October 2026, 11:59 PM PDT = Monday 19 October, about 5:59 PM Melbourne time. Only your first submitted entry counts, so post once, when it's complete.

## Already done (by the agents, while you were out)
- Code, tests, eval, demo page, draft post: all in this folder, committed in git.
- GitHub repo is public; GitHub Pages serves the demo from `docs/`.

## 1. Repo public + demo page: DONE (13 Oct)
Repo: https://github.com/Otto-Deviant1904/arvo  Demo: https://otto-deviant1904.github.io/arvo/

## 2. Gemma smoke test on GitHub Actions: DONE
Run 38347559687 (gemma4:e2b on a CPU-only runner, passed) is linked in the post.

## 3. Upload the video
`video/arvo_silent.mp4` (3:35, silent, captions burned in). Title, description with chapters and tags: `video/YOUTUBE.md`. Thumbnail: `video/slides/thumbnail.png`. Paste the YouTube link into the Demo section of `DEV_POST.md`.

## 4. Find a first user (this is where the bonus points are)
Ideal: anyone you know who does NDIS support work on an ABN, or who used to. Lots of students in Melbourne do. Also good: a plan manager, a support coordinator, or someone who invoices for a family member's supports.

A 15-minute session:
1. Show the demo page, or run `python -m arvo serve` on your laptop and let them type last week's diary **with the names changed** (privacy: change participant names and NDIS numbers before they type anything).
2. Ask, and write down their exact words:
   - How do you do your invoices now, and how long does it take?
   - Did Arvo get the times and the item numbers right? What did it get wrong?
   - The restrictive-practice flag: useful, annoying, or scary? Would you want it?
   - Would you pay $12 a month or $99 a year for this? What would make it worth it?
   - What would you want it to do next?
3. If they agree, quote them by first name (or anonymously) in the post. **Never write a user section without a real user.** If you don't find one, delete the "My First User" section from the post.

## 4. Fill and publish the post (15 min)
Open `DEV_POST.md`. Fill every `[BRACKETED]` part (demo link, first user or delete that section). Publish on DEV with the tags `devchallenge` and `hf26challenge` (the challenge template adds them). Keep the first line, the submission link.

## 5. After the deadline
Any commit after the deadline must be noted in the README. Easiest: don't push after you submit.
