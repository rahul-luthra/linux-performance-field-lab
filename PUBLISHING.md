# Where and how to showcase this work

## Recommended home: GitHub repository plus GitHub Pages

Use a public repository for the source, raw public evidence and case study, with GitHub Pages serving the interactive saved-results report. A reviewer can explore the result first and inspect the implementation afterward. GitHub Pages serves the static report; the Java app remains private on the lab VM.

1. Extract the supplied `linux-performance-field-lab.zip` into a clean directory. It is built from explicit public-file lists and excludes SSH keys, connection files, raw JVM recordings and local build outputs. Do not upload the parent Downloads folder.
2. Create a public GitHub repository named `linux-performance-field-lab`.
3. Upload the extracted project contents to its root, including `README.md`, `APP_CASE_STUDY.md`, `app/`, `results/` and `docs/`. Preserve their folder structure. Choose a code license before publishing; a small original project like this can use MIT or Apache-2.0 if that matches your preference.
4. In the repository, select **Settings → Pages → Build and deployment → Deploy from a branch**. Choose **main** and **/docs**, then save.
5. Wait for the Pages deployment to finish. The expected project address is `https://YOUR-USERNAME.github.io/linux-performance-field-lab/`; use the actual published URL GitHub shows.
6. Add that URL to the repository's About website field and to the top of the README. Pin the repository on your GitHub profile.
7. Put the Pages URL on your résumé and in emails; link the repository as the supporting source.

The prepared `docs/index.html` is self-contained. It visualizes saved measurements and has no connection to the VM. GitHub documents branch/folder publishing in [Configure a publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

If you prefer Git over browser uploads, initialize a repository only inside the clean extracted folder, add the project files, commit, add your new repository's remote URL and push to main. Inspect the staged files before publishing. The release already omits private material; retain its `.gitignore`.

## Discovery: LinkedIn

Publish a short post leading with the measured finding, attach the report screenshot, and link the public report and repository. Add the report to your profile's Featured section, which supports external links. See [LinkedIn's Featured guidance](https://www.linkedin.com/help/linkedin/answer/a550399/manage-featured-samples-of-your-work-on-your-linkedin-profile).

Suggested post, after replacing the two link placeholders:

> I tested how CPU contention affects a small Java service on a two-CPU Linux VM. At the same 4 requests/second, p95 latency rose from 92 ms to 411 ms, while every request still succeeded.
>
> I compared HTTP timings with Linux CPU/runnable metrics, handler thread CPU time, perf counters and a Java Flight Recorder profile. A repeat confirmed the slowdown. Capping the background workload to one CPU reduced contention-window p95 to 177 ms, with a cost to the background job and some requests still above the illustrative latency budget.
>
> The interactive report, source, raw public evidence, methodology and limitations are available here:
> Report: YOUR-PUBLISHED-REPORT-LINK
> Source: YOUR-REPOSITORY-LINK

Avoid presenting the cross-run improvement as a production guarantee. Keep the repeated uncapped runs and the single capped run visible.

## Depth: DEV Community or your existing blog

Use `APP_CASE_STUDY.md` as the article draft. Suggested title: **Why p95 latency rose from 92 ms to 411 ms on a two-CPU Linux VM**. Add the report screenshot near the start, then show the three-run table, diagnostic reasoning, mitigation tradeoff and reproduction steps. Link back to the GitHub report and source.

DEV supports Markdown articles and drafts; if you publish the article first on your own site, use its canonical URL when cross-posting. See [DEV's publishing guide](https://dev.to/help/writing-editing-scheduling).

## A short walkthrough

Record roughly two minutes: show the constant request rate, switch between measured runs, explain the gap between handler wall time and thread CPU time, inspect quota verification, and end with what remains uncertain. Put the report link beneath the video. A short walkthrough can help a reviewer decide whether to inspect the deeper evidence.

## Resume description

Linux performance lab: built and deployed a constrained Java HTTP service, measured p95 latency under controlled CPU contention, cross-checked Linux/per-process/JVM evidence, and evaluated a cgroup CPU-quota mitigation. Published reproducible source and an interactive evidence report.
