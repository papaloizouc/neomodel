from py2neo import neo4j
from .indexbatch import IndexBatch
from .relationship import RelationshipInstaller, RelationshipManager
from lucenequerybuilder import Q
import types
import sys
import os


class NeoDB(object):
    """ Manage and cache connections to neo4j """

    def __init__(self, graph_db):
        self.client = graph_db
        self.category_cache = {}

    def category(self, name):
        """ Retrieve category node by name """
        category_index = self.client.get_or_create_index(neo4j.Node, 'Category')

        if name not in self.category_cache:
            category = category_index.get_or_create('category', name, {'category': name})
            self.category_cache[name] = category

        return self.category_cache[name]


def connection_adapter():
    try:
        return connection_adapter.db
    except AttributeError:
        url = os.environ.get('NEO4J_URL', 'http://localhost:7474/db/data/')
        graph_db = neo4j.GraphDatabaseService(url)
        connection_adapter.db = NeoDB(graph_db)
        return connection_adapter.db


class NodeIndexManager(object):
    def __init__(self, node_class, index):
        self.node_class = node_class
        self._index = index

    def search(self, query=None, **kwargs):
        """ Load multiple nodes via index """
        for k, v in kwargs.iteritems():
            # TODO use client.get_properties!!!
            p = self.node_class.get_property(k)
            if not p:
                raise NoSuchProperty(k)
            if not p.is_indexed:
                raise PropertyNotIndexed(k)
            p.validate(v)

        if not query:
            query = reduce(lambda x, y: x & y, [Q(k, v) for k, v in kwargs.iteritems()])

        result = self._index.query(str(query))
        nodes = []

        for node in result:
            properties = node.get_properties()
            neonode = self.node_class(**properties)
            neonode._node = node
            nodes.append(neonode)
        return nodes

    def get(self, query=None, **kwargs):
        """ Load single node via index """
        nodes = self.search(query, **kwargs)
        if len(nodes) == 1:
            return nodes[0]
        elif len(nodes) > 1:
            raise Exception("Multiple nodes returned from query, expected one")
        else:
            raise Exception("No nodes found")


class StructuredNodeMeta(type):
    def __new__(cls, name, bases, dct):
        cls = super(StructuredNodeMeta, cls).__new__(cls, name, bases, dct)
        if cls.__name__ != 'StructuredNode':
            db = connection_adapter()
            index = db.client.get_or_create_index(neo4j.Node, name)
            cls.index = NodeIndexManager(cls, index)
        return cls


class StructuredNode(RelationshipInstaller):
    """ Base class for nodes requiring formal declaration """

    __metaclass__ = StructuredNodeMeta

    @classmethod
    def get_property(cls, name):
        node_property = getattr(cls, name)
        if not node_property or not issubclass(node_property.__class__, Property):
            Exception(name + " is not a Property of " + cls.__name__)
        return node_property

    def __init__(self, *args, **kwargs):
        self._validate_args(kwargs)
        self._node = None
        self._db = connection_adapter()
        self._type = self.__class__.__name__
        self._index = self.client.get_or_create_index(neo4j.Node, self._type)

        super(StructuredNode, self).__init__(*args, **kwargs)

    def __setattr__(self, key, value):
        if key.startswith('_'):
            self.__dict__[key] = value
            return
        prop = self.__class__.get_property(key)
        if prop.validate(value):
            self.__dict__[key] = value

    @property
    def client(self):
        return self._db.client

    @property
    def properties(self):
        """ Return properties and values of a node """
        props = {}
        for key, value in self.__dict__.iteritems():
            if not key.startswith('_')\
                and not isinstance(value, types.MethodType)\
                and not isinstance(value, RelationshipManager)\
                and value != None:
                    props[key] = value
        return props

    def _validate_args(self, props):
        """ Validate dict and set node properties """
        for key, node_property in self.__class__.__dict__.iteritems():
            if key in props:
                value = props[key]
            else:
                value = None
            if isinstance(node_property, Property):
                node_property.validate(value)
            self.__dict__[key] = value

    def _create(self, props):
        relation_name = self._type.upper()
        self._node, rel = self.client.create(props,
                (self._db.category(self._type), relation_name, 0))
        if not self._node:
            Exception('Failed to create new ' + self._type)

        # Update indexes
        try:
            self._update_index(props)
        except Exception:
            exc_info = sys.exc_info()
            self.delete()
            raise exc_info[1], None, exc_info[2]

    def _update_index(self, props):
        batch = IndexBatch(self._index)
        for key, value in props.iteritems():
            node_property = self.__class__.get_property(key)
            if node_property.unique_index:
                batch.add_if_none(key, value, self._node)
            elif node_property.index:
                batch.add(key, value, self._node)
        if 200 in [r.status for r in batch.submit()]:
            raise NotUnique('A supplied value is not unique' + r.uri)

    def save(self):
        if self._node:
            self._node.set_properties(self.properties)
            self._index.remove(entity=self._node)
            self._update_index(self.properties)
        else:
            self._create(self.properties)
        return self

    def delete(self):
        if self._node:
            to_delete = self._node.get_relationships()
            to_delete.append(self._node)
            self.client.delete(*to_delete)
            self._node = None
        else:
            raise Exception("Node has not been saved so cannot be deleted")
        return True


class Property(object):
    def __init__(self, unique_index=False, index=False, optional=False):
        self.optional = optional
        if unique_index and index:
            raise Exception("unique_index and index are mutually exclusive")
        self.unique_index = unique_index
        self.index = index

    @property
    def is_indexed(self):
        return self.unique_index or self.index


class StringProperty(Property):
    def validate(self, value):
        if value == None and self.optional:
            return True
        if isinstance(value, (str, unicode)):
            return True
        else:
            raise TypeError("Object of type str expected got " + str(value))


class IntegerProperty(Property):
    def validate(self, value):
        if value == None and self.optional:
            return True
        if isinstance(value, (int, long)):
            return True
        else:
            raise TypeError("Object of type int or long expected")


class FloatProperty(Property):
    def validate(self, value):
        if value == None and self.optional:
            return True
        if isinstance(value, (float)):
            return True
        else:
            raise TypeError("Object of type int or long expected")


class BoolProperty(Property):
    def validate(self, value):
        if value == None and self.optional:
            return True
        if isinstance(value, (int, long)):
            return True
        else:
            raise TypeError("Object of type int or long expected")


class NoSuchProperty(Exception):
    pass


class PropertyNotIndexed(Exception):
    pass


class NotUnique(Exception):
    pass
