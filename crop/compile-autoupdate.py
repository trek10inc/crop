with open('autoupdater.py') as f:
    compiled_autoupdater = []
    content = f.readlines()
    for x in content:
      compiled_autoupdater.append('"%s",' % (x.rstrip()))

print(compiled_autoupdater)