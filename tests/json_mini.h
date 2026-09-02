// tests/json_mini.h -- TE-62: a minimal, dependency-free JSON reader for
// this suite's own test<->oracle protocol (a C++ test process invokes a
// Python oracle as a subprocess and parses its JSON stdout). Not a
// general-purpose JSON library -- it covers exactly the value shapes this
// suite's oracles emit (object, array, integer, string, null, and
// negative integers) and is deliberately narrow so its own correctness is
// easy to read in full. No third-party dependency is available to this
// project's test build, and the suite's own protocol does not need one.
#ifndef SEMB_TESTS_JSON_MINI_H
#define SEMB_TESTS_JSON_MINI_H

#include <cstdint>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace json_mini {

enum class Kind { kNull, kInt, kString, kArray, kObject };

struct Value {
  Kind kind = Kind::kNull;
  int64_t as_int = 0;
  std::string as_string;
  std::vector<Value> as_array;
  std::map<std::string, Value> as_object;

  bool is_null() const { return kind == Kind::kNull; }
  int64_t i() const {
    if (kind != Kind::kInt) throw std::runtime_error("json_mini: not an int");
    return as_int;
  }
  const std::string& s() const {
    if (kind != Kind::kString) throw std::runtime_error("json_mini: not a string");
    return as_string;
  }
  const std::vector<Value>& arr() const {
    if (kind != Kind::kArray) throw std::runtime_error("json_mini: not an array");
    return as_array;
  }
  const Value& operator[](const std::string& key) const {
    if (kind != Kind::kObject) throw std::runtime_error("json_mini: not an object");
    auto it = as_object.find(key);
    if (it == as_object.end()) throw std::runtime_error("json_mini: missing key '" + key + "'");
    return it->second;
  }
};

class Parser {
 public:
  explicit Parser(const std::string& text) : s_(text), i_(0) {}

  Value Parse() {
    SkipWs();
    Value v = ParseValue();
    SkipWs();
    return v;
  }

 private:
  const std::string& s_;
  size_t i_;

  void SkipWs() {
    while (i_ < s_.size() && (s_[i_] == ' ' || s_[i_] == '\t' || s_[i_] == '\n' || s_[i_] == '\r'))
      ++i_;
  }
  char Peek() {
    if (i_ >= s_.size()) throw std::runtime_error("json_mini: unexpected end of input");
    return s_[i_];
  }
  char Take() {
    char c = Peek();
    ++i_;
    return c;
  }
  void Expect(char c) {
    if (Take() != c) throw std::runtime_error(std::string("json_mini: expected '") + c + "'");
  }

  Value ParseValue() {
    SkipWs();
    char c = Peek();
    if (c == '{') return ParseObject();
    if (c == '[') return ParseArray();
    if (c == '"') return ParseString();
    if (c == 'n') {
      Expect('n'); Expect('u'); Expect('l'); Expect('l');
      return Value{};
    }
    return ParseInt();
  }

  Value ParseObject() {
    Value v;
    v.kind = Kind::kObject;
    Expect('{');
    SkipWs();
    if (Peek() == '}') { Take(); return v; }
    for (;;) {
      SkipWs();
      Value key = ParseString();
      SkipWs();
      Expect(':');
      Value val = ParseValue();
      v.as_object[key.as_string] = val;
      SkipWs();
      char c = Take();
      if (c == '}') break;
      if (c != ',') throw std::runtime_error("json_mini: expected ',' or '}' in object");
    }
    return v;
  }

  Value ParseArray() {
    Value v;
    v.kind = Kind::kArray;
    Expect('[');
    SkipWs();
    if (Peek() == ']') { Take(); return v; }
    for (;;) {
      v.as_array.push_back(ParseValue());
      SkipWs();
      char c = Take();
      if (c == ']') break;
      if (c != ',') throw std::runtime_error("json_mini: expected ',' or ']' in array");
      SkipWs();
    }
    return v;
  }

  Value ParseString() {
    Value v;
    v.kind = Kind::kString;
    Expect('"');
    std::string out;
    for (;;) {
      char c = Take();
      if (c == '"') break;
      if (c == '\\') {
        char e = Take();
        switch (e) {
          case '"': out.push_back('"'); break;
          case '\\': out.push_back('\\'); break;
          case '/': out.push_back('/'); break;
          case 'n': out.push_back('\n'); break;
          case 't': out.push_back('\t'); break;
          case 'r': out.push_back('\r'); break;
          default: out.push_back(e); break;
        }
      } else {
        out.push_back(c);
      }
    }
    v.as_string = out;
    return v;
  }

  Value ParseInt() {
    Value v;
    v.kind = Kind::kInt;
    size_t start = i_;
    if (Peek() == '-') Take();
    while (i_ < s_.size() && s_[i_] >= '0' && s_[i_] <= '9') ++i_;
    v.as_int = std::stoll(s_.substr(start, i_ - start));
    return v;
  }
};

inline Value Parse(const std::string& text) { return Parser(text).Parse(); }

}  // namespace json_mini

#endif  // SEMB_TESTS_JSON_MINI_H
