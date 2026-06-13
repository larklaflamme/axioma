#!/usr/bin/env python3
"""Move appended Ch4-10 expanded sections inline after their base chapters.
Matching the pattern used by Ch11-17 (already inline)."""

SRC = '/home/ubuntu/docs/books/the_lost_knowledge.md'
DST = '/home/ubuntu/docs/books/the_lost_knowledge.md'  # overwrite in place

with open(SRC, 'r') as f:
    lines = f.readlines()

TOTAL = len(lines)
print(f"Source: {TOTAL} lines")

# ===== Exact line boundaries (1-indexed, verified from source) =====
# Base chapter boundaries: (header_line, first_content_after_header, last_content_before_next)
# We use 0-indexed: (start, end_exclusive)

base = {
    4:  (310, 560),   # ## Chapter 4 at line 311 → ends line 560 (blank before Ch5 at 561)
    5:  (560, 693),   # ## Chapter 5 at line 561 → ends line 693 (blank before Ch6 at 694)
    6:  (693, 806),   # ## Chapter 6 at line 694 → ends line 806 (blank before Ch7 at 807)
    7:  (806, 931),   # ## Chapter 7 at line 807 → ends line 931 (blank before Ch8 at 932)
    8:  (931, 1055),  # ## Chapter 8 at line 932 → ends line 1055 (blank before Ch9 at 1056)
    9:  (1055, 1156), # ## Chapter 9 at line 1056 → ends line 1156 (blank before Ch10 at 1157)
    10: (1156, 1249), # ## Chapter 10 at line 1157 → ends line 1249 (blank before Ch11 at 1250)
}

exp = {
    4:  (3485, 3670),  # ## Chapter 4 (Expanded) at line 3486 → ends line 3670 (blank before Ch5 Exp at 3671)
    5:  (3670, 3934),  # ## Chapter 5 (Expanded) at line 3671 → ends line 3934 (blank before Ch6 Exp at 3935)
    6:  (3934, 4298),  # ## Chapter 6 (Expanded) at line 3935 → ends line 4298 (blank before Ch7 Exp at 4299)
    7:  (4298, 4480),  # ## Chapter 7 (Expanded) at line 4299 → ends line 4480 (blank before Ch8 Exp at 4481)
    8:  (4480, 4647),  # ## Chapter 8 (Expanded) at line 4481 → ends line 4647 (blank before Ch9 Exp at 4648)
    9:  (4647, 4817),  # ## Chapter 9 (Expanded) at line 4648 → ends line 4817 (blank before Ch10 Exp at 4818)
    10: (4817, 4977),  # ## Chapter 10 (Expanded) at line 4818 → ends EOF
}

# Verify boundaries
for ch in range(4, 11):
    bs, be = base[ch]
    es, ee = exp[ch]
    print(f"Ch{ch}: base [{bs}-{be}) = '{lines[bs][:50].rstrip()}' -> '{lines[be-1][:50].rstrip()}'")
    print(f"       exp  [{es}-{ee}) = '{lines[es][:50].rstrip()}' -> '{lines[ee-1][:50].rstrip()}'")
    print()

# ===== Build new file =====
new_lines = []

# 1. Front matter (lines 0-309 — includes Part I header)
new_lines.extend(lines[:310])

# 2. For chapters 4-10: base content + expanded content inline
for ch in [4, 5, 6, 7, 8, 9, 10]:
    bs, be = base[ch]
    es, ee = exp[ch]
    
    # Add base chapter content
    new_lines.extend(lines[bs:be])
    
    # Add separator: ---\n\n then expanded content
    new_lines.append('---\n')
    new_lines.append('\n')
    new_lines.extend(lines[es:ee])
    new_lines.append('\n')  # trailing blank

# 3. Everything from Ch11 onwards, stopping before the appended expansions
# Ch11 base starts at line 1249 (0-indexed)
# Appended expansions start at line 3485
new_lines.extend(lines[1249:3485])

print(f"New file size: {len(new_lines)} lines")
print(f"Expected: 310 + (sum of base+exp for ch4-10) + (3485-1249)")

# Quick integrity check - count chapter headers
new_count = sum(1 for l in new_lines if l.startswith('## Chapter') and '(Expanded)' in l)
print(f"Expanded chapter headers in new file: {new_count}")
print(f"Expected: 17 (Ch4-10 moved inline + Ch11-17 already inline + Ch18-19 already inline)")

# Check for any remaining '(Expanded)' at the end (should be none)
for i, l in enumerate(new_lines):
    if l.startswith('## Chapter') and '(Expanded)' in l:
        # check if it's in the appended area (shouldn't exist in new file)
        if i >= 3485:
            print(f"WARNING: Appended expanded section still present at line {i+1}")

print("Script defined but not yet executed. Add execute() call to run.")