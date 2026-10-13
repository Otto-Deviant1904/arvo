# Errata for the frozen files

`summary_wild.md`, line 5, says the wild gold was "written by hand, not by a model". That wording is wrong. The wild diaries and their gold labels were written by an AI agent; a second agent (a different model) labelled the diaries blind and agreed on 58 of 58 shifts (`eval/README.md`, "Wild set label check"). The numbers are unaffected. The frozen file is left as it was so its SHA-256 sum still matches; the generator (`eval/run_eval.py`) and the live `eval/results/summary_wild.md` are corrected.
