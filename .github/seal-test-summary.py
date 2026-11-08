#!/usr/bin/env python3
"""Print test totals from Gradle JUnit XML reports, plus a reason for every skip.

Gradle's JUnit XML carries no <skipped message>, so the reason is recovered from
the test source: the @Disabled / @Ignore / @EnabledFor* / @DisabledOn* annotation
on the method (or its class), or the assume* call inside the method body.
"""
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

ANNOT = re.compile(r'@(Disabled\w*|Enabled\w*|Ignore)\b.*')
ASSUME = re.compile(r'\b(assume\w*|Assumptions\.\w+|Assume\.\w+)\s*\(.*')


def source_for(module_root, classname):
    outer = classname.split('$')[0]
    rel = outer.replace('.', '/')
    for ext in ('.java', '.scala'):
        for sub in ('src/test/java', 'src/test/scala', 'src/test/scala/unit', 'src/test/scala/integration'):
            p = os.path.join(module_root, sub, rel + ext)
            if os.path.exists(p):
                return p
    simple = outer.rsplit('.', 1)[-1]
    hits = glob.glob(os.path.join(module_root, 'src/test/**/' + simple + '.*'), recursive=True)
    return hits[0] if hits else None


def reason_for(module_root, classname, testname):
    path = source_for(module_root, classname)
    if not path:
        return 'no source found for class'
    with open(path, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    method = re.split(r'[\[( ]', testname, 1)[0]
    decl = None
    for i, line in enumerate(lines):
        if re.search(r'\b(void|def)\s+' + re.escape(method) + r'\b', line):
            decl = i
            break
    if decl is not None:
        for j in range(decl - 1, max(-1, decl - 15), -1):
            m = ANNOT.search(lines[j])
            if m:
                return 'method annotation ' + m.group(0).strip()
            if lines[j].strip().endswith(('}', ';')) and not lines[j].strip().startswith('@'):
                break
        for j in range(decl, min(len(lines), decl + 40)):
            m = ASSUME.search(lines[j])
            if m:
                return 'assumption ' + m.group(0).strip()
    simple = classname.split('$')[0].rsplit('.', 1)[-1]
    for i, line in enumerate(lines):
        if re.search(r'\bclass\s+' + re.escape(simple) + r'\b', line):
            for j in range(i - 1, max(-1, i - 10), -1):
                m = ANNOT.search(lines[j])
                if m:
                    return 'class annotation ' + m.group(0).strip()
            break
    if not method:
        # Parameterized test: Gradle's XML keeps only the display name ("[3] arg=..."),
        # not the method, so report every assumption the class makes on its arguments.
        found = []
        for i, line in enumerate(lines):
            m = ASSUME.search(line)
            if m:
                comment = lines[i - 1].strip() if i and lines[i - 1].strip().startswith('//') else ''
                owner = ''
                for k in range(i, -1, -1):
                    d = re.search(r'\bvoid\s+(\w+)\s*\(', lines[k])
                    if d:
                        owner = d.group(1)
                        break
                found.append('%s: %s %s' % (owner, m.group(0).strip(), comment))
        if found:
            return ('parameterized-case assumption (display name only); the class assumes: '
                    + ' | '.join(found))
    return 'skipped by JUnit condition (no annotation found near ' + method + ')'


def main():
    files = sorted(glob.glob('**/build/test-results/**/TEST-*.xml', recursive=True))
    if not files:
        print('No JUnit XML test reports found')
        return 1
    per_module = {}
    skipped = []
    failed = []
    for xf in files:
        module_root = xf.split('/build/test-results/')[0]
        root = ET.parse(xf).getroot()
        stats = per_module.setdefault(module_root, [0, 0, 0, 0])
        for tc in root.iter('testcase'):
            stats[0] += 1
            cls, name = tc.get('classname'), tc.get('name')
            if tc.find('skipped') is not None:
                stats[2] += 1
                skipped.append((module_root, cls, name))
            elif tc.find('failure') is not None or tc.find('error') is not None:
                stats[3] += 1
                failed.append((cls, name))
            else:
                stats[1] += 1
    tot = [0, 0, 0, 0]
    print('==== Test results (from JUnit XML) ====')
    for mod, s in sorted(per_module.items()):
        print('%-28s tests=%d passed=%d skipped=%d failed=%d' % (mod, s[0], s[1], s[2], s[3]))
        tot = [a + b for a, b in zip(tot, s)]
    print('TOTAL tests=%d passed=%d skipped=%d failed(incl. retried attempts)=%d' % tuple(tot))
    if skipped:
        print('==== Skipped tests and reasons ====')
        for mod, cls, name in skipped:
            print('SKIPPED %s.%s -- %s' % (cls, name, reason_for(mod, cls, name)))
    if failed:
        print('==== Failed attempts (a test retried and passed also appears as passed) ====')
        for cls, name in failed:
            print('FAILED %s.%s' % (cls, name))
    return 0


if __name__ == '__main__':
    sys.exit(main())
