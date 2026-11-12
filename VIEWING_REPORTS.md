# View the interactive reports

## Open directly in your browser

**[Open the portfolio](https://rahul-luthra.github.io/linux-performance-field-lab/)** or go straight to **[the Java application report](https://rahul-luthra.github.io/linux-performance-field-lab/quotelab.html)**. The case studies link to their supporting captures and methods. The interactive reports use saved measurements.

The repository and Pages site are public. No download, GitHub sign-in, Java or Python installation is needed for online viewing.

## Why GitHub displays code

GitHub's repository file viewer displays `.html` files as source. The Raw button also does not turn a file into a hosted website. That is normal GitHub behavior; it is not a damaged report. Labels throughout this repository distinguish HTML source from an actual preview.

## Download once, then open locally

1. For offline viewing, download the fixed review snapshot:
2. Open the [review-v2 release](https://github.com/rahul-luthra/linux-performance-field-lab/releases/tag/review-v2).
3. Under **Assets**, download **linux-performance-field-lab.zip**. This tagged snapshot retains the documentation from its review date; the live site follows the latest main branch.
4. On Windows, right-click the downloaded ZIP and select **Extract All**.
5. In the extracted `linux-performance-field-lab` folder, right-click `app-report.html`, select **Open with**, and choose **Microsoft Edge**, **Google Chrome** or **Firefox**. If double-clicking opens an editor, use Open with instead.
6. Select an experiment and use **Download this run** to inspect its evidence. No server, Java/Python installation, internet access, or connection to the lab VM is needed to view the reports.

Alternatively, use the repository's **Code → Download ZIP**, extract it and open the same files. That option gives you the latest main branch; the named release is a fixed review snapshot.

## Report inventory

Use the live links for rendered reports. The source links intentionally open code on GitHub. Local file paths are for offline viewing after extraction.

| Report | View online | Local file | Source on GitHub |
|---|---|---|---|
| The Canary Failed: rolling patching and snapshot recovery | [Compare the trials](https://rahul-luthra.github.io/linux-performance-field-lab/patching.html) | `patching-report.html` | [HTML source](patching-report.html) |
| From Alert to Recovery: Java slowdown, alert and AWX remediation | [Replay the incident](https://rahul-luthra.github.io/linux-performance-field-lab/incident.html) | `incident-report.html` | [HTML source](incident-report.html) |
| Java application: all three measured runs and mitigation | [Open report](https://rahul-luthra.github.io/linux-performance-field-lab/quotelab.html) | `app-report.html` | [HTML source](app-report.html) |
| Memory: six fault/correction tests and three HTTP/GC experiments | [Open investigation](https://rahul-luthra.github.io/linux-performance-field-lab/memory.html) | `memory-report.html` | [HTML source](memory-report.html) |
| Storage/NFS: ten measured local/network/server-I/O cases | [Open investigation](https://rahul-luthra.github.io/linux-performance-field-lab/storage.html) | `storage-report.html` | [HTML source](storage-report.html) |
| Network: delay, loss, bandwidth and application-wait experiments | [Open investigation](https://rahul-luthra.github.io/linux-performance-field-lab/network.html) | `network-report.html` | [HTML source](network-report.html) |
| Service reliability through dependency slowdowns, outage and recovery | [Open investigation](https://rahul-luthra.github.io/linux-performance-field-lab/reliability.html) | `reliability-report.html` | [HTML source](reliability-report.html) |
| Linux host capture plus four simulated teaching scenarios | [Open scenarios](https://rahul-luthra.github.io/linux-performance-field-lab/showcase.html) | `showcase.html` | [HTML source](showcase.html) |
| First measured host CPU experiment | [Open capture](https://rahul-luthra.github.io/linux-performance-field-lab/cpu-lab.html) | `results/cpu-lab.html` | [HTML source](results/cpu-lab.html) |
| Repeated host CPU experiment | [Open capture](https://rahul-luthra.github.io/linux-performance-field-lab/cpu-lab-repeat.html) | `results/repeat/cpu-lab.html` | [HTML source](results/repeat/cpu-lab.html) |
| Three-interval collector smoke test | [Open check](https://rahul-luthra.github.io/linux-performance-field-lab/smoke-report.html) | `results/smoke-report.html` | [HTML source](results/smoke-report.html) |
| Portfolio and case study directory | [Open portfolio](https://rahul-luthra.github.io/linux-performance-field-lab/) | `docs/index.html` | [HTML source](docs/index.html) |

`report-template.html`, `app/app-report-template.html` `memory/report-template.html` `storage/report-template.html` and `network/report-template.html` are authoring templates with data placeholders. They are not generated reports; opening them directly will not produce a working interactive report.

## Previews that render directly on GitHub

- [Application latency chart](app-latency-preview.png)
- [Full Java application report screenshot](app-preview.png)
- [Full Linux CPU report screenshot](preview.png)
- [Java application case study](APP_CASE_STUDY.md)
- [Measured host CPU results](LIVE_RESULTS.md)

## Publishing and updates

Pages publishes the `docs` folder on `main`. The root HTML reports remain self-contained offline copies. Run `python3 build_pages.py` to export all nine reports with shared navigation after changing their source outputs, then commit the generated docs files. `python3 app/analyze_app.py` also rebuilds the Pages export after updating application analysis.

See [PUBLISHING.md](PUBLISHING.md) and [GitHub's Pages documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site). No external HTML-preview proxy is used.
