## AdvisorStateWriter
## Hand-rolled JSON serialization and atomic file writes for the civ4-advisor mod.
## Python 2.4 has no `json` module, so this is a minimal serializer covering
## only the value types we actually pass in: dict, list, str, int, float, bool, None.

import os


def getStateFilePath():
	'''State output path comes from LocalConfig.py (gitignored, machine-specific - see
	LocalConfig.py.example). __file__-relative path derivation was tried and does not
	work here: the embedded interpreter reports module paths relative to its own
	Assets/Python search root regardless of which physical folder (base game vs. mod,
	even through the junction) actually supplied the file.'''
	try:
		import LocalConfig
		reload(LocalConfig)  # dev convenience - see reload(AdvisorStateWriter) note in CvCustomEventManager.py
	except ImportError:
		return None
	return LocalConfig.STATE_FILE_PATH


def _escape(s):
	out = []
	for ch in s:
		if ch == '\\':
			out.append('\\\\')
		elif ch == '"':
			out.append('\\"')
		elif ch == '\n':
			out.append('\\n')
		elif ch == '\r':
			out.append('\\r')
		elif ch == '\t':
			out.append('\\t')
		else:
			out.append(ch)
	return ''.join(out)


def toJson(value):
	if value is None:
		return 'null'
	if value is True:
		return 'true'
	if value is False:
		return 'false'
	if isinstance(value, (int, long, float)):
		return str(value)
	if isinstance(value, basestring):
		return '"%s"' % _escape(value)
	if isinstance(value, dict):
		items = []
		for key in value.keys():
			items.append('"%s": %s' % (_escape(str(key)), toJson(value[key])))
		return '{%s}' % ', '.join(items)
	if isinstance(value, (list, tuple)):
		items = [toJson(item) for item in value]
		return '[%s]' % ', '.join(items)
	raise TypeError('AdvisorStateWriter.toJson: unsupported type %s' % type(value))


def writeStateFile(path, state):
	'Atomically write state (a dict) to path as JSON: write to a temp file, then rename.'
	if path is None:
		return
	stateDir = os.path.dirname(path)
	if not os.path.exists(stateDir):
		os.makedirs(stateDir)
	tempPath = path + '.tmp'
	f = open(tempPath, 'w')
	try:
		f.write(toJson(state))
	finally:
		f.close()
	if os.path.exists(path):
		os.remove(path)
	os.rename(tempPath, path)
