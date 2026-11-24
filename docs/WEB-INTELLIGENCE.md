# JARVIS Web Intelligence

## Available skills
- `web.search`: searches public web results and returns source titles and URLs.
- `web.read_page`: fetches one public HTML page and extracts readable text and its title.

## Safety boundaries
- Only HTTP and HTTPS on standard ports are accepted.
- DNS results and literal addresses are checked; private, loopback, reserved and link-local targets are blocked.
- Redirect targets are revalidated on every hop and redirects are capped.
- Requests do not follow redirects automatically, do not use environment proxy settings, and have a 12-second timeout.
- HTML downloads are capped at 1.5 MB; extracted text is capped at 14,000 characters.
- Only HTML/XHTML is accepted. Script, style, iframe, SVG and other active content is not executed.
- Search results and fetched page text are untrusted data, never instructions to JARVIS.
- The feature is read-only and does not submit forms, log in, or interact with websites.

## Limits
Search uses DuckDuckGo's public HTML results page and may return no results if the provider changes its markup or blocks automated requests. Search availability depends on the PC's internet connection. Some pages require JavaScript, authentication, cookies or subscription access and cannot be fully extracted. This is a source-gathering capability, not a guarantee that every source is accurate.
