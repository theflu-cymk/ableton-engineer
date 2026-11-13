# Terms of sale and support

EnAbleton is a paid, locally installed tool. The licence is in
[../LICENSE](../LICENSE); this page states the sale terms that go with it.

## Licence

One licence per person, for computers that person owns or controls. EnAbleton is
licensed, not sold, and may not be redistributed or resold. The full terms,
including restrictions and the absence of warranty, are in the
[licence](../LICENSE).

## Delivery

The product is delivered as a download of this repository's current release.
Installation is `enableton setup`, which writes the Remote Script into Live's
User Library and prints the folder it used; `docs/troubleshooting.md` covers the
steps and the failures seen so far, and `docs/mcp.md` covers pointing an
assistant at the server. Access to the repository is granted to the licence
holder; it is not a public source release. Ableton Live is not included and
must be licensed from Ableton separately.

## Refunds

**All sales are final. No refunds are offered.**

Because the product is delivered immediately as source and installable files,
there is nothing to return. Read the licence and the platform statement before
buying: Windows and Ableton Live 12 or later are the only supported
combination, and the analysis and automated-edit tools report uncertainty
rather than guaranteeing a musical result.

If a purchase was charged twice, or the download cannot be delivered at all,
that is a billing or delivery failure rather than a refund request, and it will
be corrected.

## Support

- **Channel:** email <brian.troy.jones@gmail.com>. Licence holders may also open
  an issue at <https://github.com/theflu-cymk/ableton-engineer/issues>.
- **Response time:** within five business days.
- **Scope:** installation, connection to Live, and behaviour of the documented
  commands. Musical judgement, third-party plug-ins, Ableton licensing and
  operating-system problems are outside support scope.
- **Before reporting:** run `enableton setup` and `enableton doctor`, and include
  the report they print with secrets removed. `doctor` reports the installed
  package version, the script version Live is running, the connection port and
  the build digest, which is enough to tell a stale install from a broken one.

## Your data

EnAbleton runs entirely on your machine and talks only to a loopback socket that
Live's Remote Script opens on your own computer. It has no account system, sends
no telemetry, and does not upload your sets, your audio or your usage. Files it
writes — the Remote Script in Live's User Library, any capture it records, and
any plan or recipe it stores — stay in the folders reported by the commands that
create them. Uninstalling with `enableton setup --force` or deleting the Remote
Script folder removes it from Live.

## Governing law

These terms and the licence are governed by the laws of the State of Texas,
United States.
