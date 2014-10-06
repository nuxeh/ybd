import yaml

def load_assembly(foo):
  filename = "./sets/" + foo + ".def"

  assembly = []

  try:
    with open(filename) as f:
       text = f.read()
  
    assembly = yaml.safe_load(text)

  except:
	return None

  return assembly

def get(thing, value):
	val = []
	try:
		val = thing[value]
	except:
		pass
	return val

def graph_count(name):
	try:
	    graph[name] = graph[name] + 1

	except:
	    graph[name] = 0

def walk(name, graph):
	print
	print
	print 'Walk %s' % name
	this = load_assembly(name)
	graph_count(name)

	for dependency in get(this, 'build-depends'):
	    print '%s build-dependency is %s' % (get(this, 'name'), dependency)
	    graph_count(dependency)
	    walk(dependency, graph)

	for content in get(this, 'contents'):
		print '%s contains %s, check for build-dependencies:' % (name, get(content, 'name'))
		name = get(content, 'name').split('|')[0]
		graph_count(name)
		print '-- %s' % get(content, 'build-depends')
		for dep in get(content, 'build-depends'):
		    graph_count(dep)
		if load_assembly(get(content, 'name')):
		    walk(get(content, 'name'), graph)

graph = {}
walk('first-set', graph)

print graph


