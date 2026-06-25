import glob, os
files = glob.glob('conf/**/*.mp3', recursive=True)
print('Found', len(files), 'mp3 files')
for p in files:
    try:
        os.remove(p)
        print('Deleted:', p)
    except Exception as e:
        print('Error deleting', p, e)
