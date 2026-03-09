import sys
with open('generate_site.py','r',encoding='utf-8') as f:
    for i,line in enumerate(f, start=1):
        if 30<=i<=60:
            sys.stdout.write(f"{i:4d}: {line.rstrip()!r}\n")
