# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in geocoder, please report it
privately rather than opening a public issue — this gives time to investigate
and release a fix before details are public.

To report a vulnerability, contact the maintainer directly:
**https://www.pangaeatech.com/contact**

Please include as much of the following as you can:

- A description of the vulnerability and its potential impact
- Steps to reproduce it (a minimal example is ideal)
- The affected version/commit
- Any suggested fix or mitigation, if you have one

## What to expect

- Please allow a reasonable amount of time for a response before disclosing
  publicly.
- You'll be credited in the fix/release notes if you'd like, unless you
  prefer to remain anonymous.

## Scope

This project authenticates to multiple third-party services, including Google
and Geocodio. Vulnerabilities of particular interest include:

- Anything that could leak or mishandle API keys or credentials
- Anything that could cause excessive charges to a user's account
- Dependency vulnerabilities with a realistic exploit path in this project's
  usage

Issues in third-party services this project depends on (Google Maps, Geocodio,
etc.) should be reported to those services directly, not here.
