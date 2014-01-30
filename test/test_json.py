import unittest
import json

from neomodel import (
    StructuredNode,
    StringProperty, IntegerProperty,
    RelationshipTo, RelationshipFrom,
    json_encode, JsonEncoder
    )


class Country(StructuredNode):
    code = StringProperty(unique_index=True, required=True)
    inhabitant = RelationshipFrom('Person', 'IS_FROM')
    json_attrs = ["code", "inhabitant"]


class Person(StructuredNode):
    name = StringProperty(unique_index=True)
    age = IntegerProperty(index=True, default=0)
    country = RelationshipTo(Country, 'IS_FROM')


class NonSerializable:
    pass


class TestA(unittest.TestCase):
    def setUp(self):
        pass

    def test_a(self):
        jim = Person(name='Jim', age=3)
        jim.save()
        germany = Country(code='DE')
        germany.save()
        jim.country.connect(germany)
        jim.delete()
        germany.delete()
        assert germany.__json__() == {'code': 'DE'}
        assert jim.__json__() == {'age': 3, 'name': 'Jim'}
        # ensure encode works fine
        assert json_encode(jim) == json.dumps({'age': 3, 'name': 'Jim'})
        assert json_encode(germany) == json.dumps({'code': 'DE'})
        # ensure JsonEncoder works with cls arg
        assert json_encode(germany) == json.dumps(germany, cls=JsonEncoder)
        assert json_encode(jim) == json.dumps(jim, cls=JsonEncoder)
        # assert JsonEncoder doesn't break default behaviour
        assert json_encode([1, 2, 3]) == json.dumps([1, 2, 3], cls=JsonEncoder)
        assert json_encode({"a": 1, "b": 2}) == json.dumps(
            {"a": 1, "b": 2}, cls=JsonEncoder)

        must_raise = lambda: json_encode(NonSerializable())
        self.assertRaises(TypeError, must_raise)


unittest.main()
