# View the reports while the repository is private

## Why GitHub displays code

GitHub's repository file viewer displays `.html` files as source. The Raw button also does not turn a file into a hosted website. That is normal GitHub behavior; it is not a damaged report. Labels throughout this repository distinguish HTML source from an actual preview.

## Download once, then open locally

1. Sign in to GitHub with access to this private repository.
2. Open the [review-v1 release](https://github.com/rahul-luthra/linux-performance-field-lab/releases/tag/review-v1).
3. Under **Assets**, download **linux-performance-field-lab.zip**. The release and its assets inherit the repository's private access.
4. On Windows, right-click the downloaded ZIP and select **Extract All**.
5. In the extracted `linux-performance-field-lab` folder, right-click `app-report.html`, select **Open with**, and choose **Microsoft Edge**, **Google Chrome** or **Firefox**. If double-clicking opens an editor, use Open with instead.
6. Select an experiment and use **Download this run** to inspect its evidence. No server, Java/Python installation, internet access, or connection to the lab VM is needed to view the reports.

Alternatively, use the repository's **Code → Download ZIP**, extract it and open the same files. That option gives you the latest main branch; the named release is a fixed review snapshot.

## Report inventory

The links in the source column intentionally open code on GitHub. Use the local file path after extracting the ZIP to see each rendered page.

| Report | Local file to open in a browser | Source on GitHub |
|---|---|---|
| Java application: all three measured runs and mitigation | `app-report.html` | [HTML source](app-report.html) |
| Linux host capture plus four simulated teaching scenarios | `showcase.html` | [HTML source](showcase.html) |
| First measured host CPU experiment | `results/cpu-lab.html` | [HTML source](results/cpu-lab.html) |
| Repeated host CPU experiment | `results/repeat/cpu-lab.html` | [HTML source](results/repeat/cpu-lab.html) |
| Three-interval collector smoke test | `results/smoke-report.html` | [HTML source](results/smoke-report.html) |
| Future Pages entry point, identical to the Java report | `docs/index.html` | [HTML source](docs/index.html) |

`report-template.html` and `app/app-report-template.html` are authoring templates with data placeholders. They are not generated reports; opening them directly will not produce a working interactive report.

## Previews that render directly on GitHub

- [Application latency chart](app-latency-preview.png)
- [Full Java application report screenshot](app-preview.png)
- [Full Linux CPU report screenshot](preview.png)
- [Java application case study](APP_CASE_STUDY.md)
- [Measured host CPU results](LIVE_RESULTS.md)

## Public hosting later

No website has been published for this private review. Normal GitHub Pages publication can expose a site publicly even when its repository is private, depending on plan and access settings, so repository privacy alone is not a private-site guarantee. See [GitHub's Pages documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site).

When you decide to publish, follow [PUBLISHING.md](PUBLISHING.md). No external HTML-preview proxy is needed for this review.
