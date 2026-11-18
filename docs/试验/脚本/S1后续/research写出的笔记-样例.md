# json.dump 的 ensure_ascii：默认值是什么，设成 False 会怎样

调研日期：2026-11-17
依据：Python 官方文档（英文版为准，中文版作对照）、CPython 源码、本机实测。没有参考任何博客或问答网站。

## 一句话结论

- **默认值是 `True`。**
- **默认（True）时**：所有非 ASCII 字符（比如中文、emoji）和不可打印字符都会被写成 `\uXXXX` 这种转义形式，输出里只剩可打印的 ASCII 字符。
- **设成 `False` 时**：字符原样输出（中文就是中文），只有 JSON 规定必须转义的那几样还会转义：双引号、反斜杠、U+0000 到 U+001F 的控制字符。
- 两种写法都是合法 JSON，读回来得到的数据完全一样，区别只在文件里"长什么样"。
- 用 `False` 时要自己保证打开文件用的编码（建议 `encoding="utf-8"`）能存下这些字符，否则写文件时会报 `UnicodeEncodeError`。

```python
json.dumps("中文é😀")                      # '"\u4e2d\u6587\u00e9\ud83d\ude00"'
json.dumps("中文é😀", ensure_ascii=False)  # '"中文é😀"'
```

## 一、官方文档明确写了的内容

读的是 `https://docs.python.org/3/library/json.html`，抓取时页面标题显示 **Python 3.15.2 documentation**；中文版 `https://docs.python.org/zh-cn/3/library/json.html` 标题为 **Python 3.15.2 文档**。

### 1. 默认值是 True

文档里的函数签名：

> `json.dump(obj, fp, *, skipkeys=False, ensure_ascii=True, check_circular=True, allow_nan=True, cls=None, indent=None, separators=None, default=None, sort_keys=False, **kw)`

出处：<https://docs.python.org/3/library/json.html#json.dump>

`json.dumps` 的签名里同样是 `ensure_ascii=True`，并且文档说它的参数含义和 `dump()` 一样（"The arguments have the same meaning as in `dump()`."）。
出处：<https://docs.python.org/3/library/json.html#json.dumps>

### 2. True 和 False 各自的效果

`json.dump` 的参数说明原文：

> **ensure_ascii** (bool) – If `True` (the default), the output is guaranteed to have all incoming non-ASCII and non-printable characters escaped. If `False`, all characters will be outputted as-is, except for the characters that must be escaped: quotation mark, reverse solidus, and the control characters U+0000 through U+001F.

出处：<https://docs.python.org/3/library/json.html#json.dump>

中文版对应原文：

> **ensure_ascii** (bool) -- 如果为 `True` (默认值)，输出将确保对所有输入的非 ASCII 和不可打印字符进行转义。 如果为 `False`，则所有字符将被原样输出，只有必须被转义的字符除外：引号、反斜线，以及 U+0000 至 U+001F 范围的控制字符。

出处：<https://docs.python.org/zh-cn/3/library/json.html#json.dump>

`JSONEncoder` 类的说明里是同一个意思（它的签名里也是 `ensure_ascii=True`）：

> If *ensure_ascii* is true (the default), the output is guaranteed to have all incoming non-ASCII and non-printable characters escaped. If *ensure_ascii* is false, all characters will be output as-is, except for the characters that must be escaped: quotation mark, reverse solidus, and the control characters U+0000 through U+001F.

出处：<https://docs.python.org/3/library/json.html#json.JSONEncoder>

### 3. json.dump 写出去的是 str，不是 bytes

`fp` 参数的说明原文：

> **fp** (file-like object) – The file-like object *obj* will be serialized to. The `json` module always produces `str` objects, not `bytes` objects, therefore `fp.write()` must support `str` input.

出处：<https://docs.python.org/3/library/json.html#json.dump>

也就是说：`json` 模块只负责产出文本，把文本变成字节（编码）是文件对象的事。

### 4. "字符编码"一节怎么说

> The RFC requires that JSON be represented using either UTF-8, UTF-16, or UTF-32, with UTF-8 being the recommended default for maximum interoperability.
>
> As permitted, though not required, by the RFC, this module's serializer sets *ensure_ascii=True* by default, thus escaping the output so that the resulting strings only contain printable ASCII characters.
>
> Other than the *ensure_ascii* parameter, this module is defined strictly in terms of conversion between Python objects and Unicode strings, and thus does not otherwise directly address the issue of character encodings.
>
> The RFC prohibits adding a byte order mark (BOM) to the start of a JSON text, and this module's serializer does not add a BOM to its output. …
>
> The RFC does not explicitly forbid JSON strings which contain byte sequences that don't correspond to valid Unicode characters (e.g. unpaired UTF-16 surrogates), but it does note that they may cause interoperability problems. By default, this module accepts and outputs (when present in the original `str`) code points for such sequences.

出处：<https://docs.python.org/3/library/json.html#character-encodings>

中文版对应的关键两句：

> 正如 RFC 所允许（但不要求）的那样，此模块的序列化器默认设置 *ensure_ascii=True*，从而对输出进行转义，使结果字符串只包含可打印的 ASCII 字符。
>
> 除了 *ensure_ascii* 参数以外，此模块严格按照 Python 对象和 Unicode 字符串 之间的转换来定义，因此不会直接处理字符编码的问题。

出处：<https://docs.python.org/zh-cn/3/library/json.html#character-encodings>

从这一节能直接读出来的：

- 默认转义是 RFC 允许但不强制的做法，所以 True 和 False 的输出都符合 RFC，都是合法 JSON。
- RFC 推荐用 UTF-8。
- 模块不管编码，也不会写 BOM。

### 5. 其他相关的文档内容

- 命令行工具有对应开关 `--no-ensure-ascii`："Disable escaping of non-ascii characters, see `json.dumps()` for more information."，3.9 版加入。
  出处：<https://docs.python.org/3/library/json.html#cmdoption-json-no-ensure-ascii>
- 脚注 [1]：JSON 允许字符串里直接出现 U+2028（行分隔符）和 U+2029（段分隔符），而 JavaScript（ECMAScript 5.1）不允许。
  出处：<https://docs.python.org/3/library/json.html> 页面底部 Footnotes [1]
  这条和 `ensure_ascii=False` 有关：见下面第三部分的实测。

## 二、从 CPython 源码确认的内容（文档没有逐字写，但源码可证）

源码取自 `main` 分支，抓取时 `main` 的最新提交是 `4497fe9889105b1abc6d633971e84ee9f78bd3b8`，下面的行号以这个版本为准。

1. **默认值**：`def dump(obj, fp, *, skipkeys=False, ensure_ascii=True, ...)`
   出处：[Lib/json/__init__.py 第 120 行](https://github.com/python/cpython/blob/4497fe9889105b1abc6d633971e84ee9f78bd3b8/Lib/json/__init__.py#L120)；`dumps` 在第 185 行，`JSONEncoder.__init__` 在 [Lib/json/encoder.py 第 105 行](https://github.com/python/cpython/blob/4497fe9889105b1abc6d633971e84ee9f78bd3b8/Lib/json/encoder.py#L105)。

2. **docstring 的说法**（`__init__.py` 第 130–133 行）：

   > If ``ensure_ascii`` is false, then the strings written to ``fp`` can contain non-ASCII and non-printable characters if they appear in strings contained in ``obj``. Otherwise, all such characters are escaped in JSON strings.

3. **dump 就是把一段段 str 交给 `fp.write`**（`__init__.py` 第 181–182 行）：

   ```python
   for chunk in iterable:
       fp.write(chunk)
   ```

   整个函数里没有任何 `encode` 操作，印证了"编码由文件对象负责"。

4. **ensure_ascii 就是在两个字符串编码函数之间二选一**（`encoder.py` 第 221–224 行，`encode()` 里第 195–198 行同理）：

   ```python
   if self.ensure_ascii:
       _encoder = encode_basestring_ascii
   else:
       _encoder = encode_basestring
   ```

5. **两个函数分别转义哪些字符**（`encoder.py` 第 18–19 行）：

   ```python
   ESCAPE = re.compile(r'[\x00-\x1f\\"\b\f\n\r\t]')      # ensure_ascii=False 用
   ESCAPE_ASCII = re.compile(r'([\\"]|[^\ -~])')          # ensure_ascii=True 用
   ```

   - False：只转义 U+0000–U+001F、反斜杠、双引号，和文档说的一致。
   - True：除了空格到 `~`（U+0020–U+007E）之外的字符全部转义。所以 U+007F（DEL）虽然属于 ASCII，也会被转义，这就是文档里"non-printable（不可打印）"指的情况。

6. **超出基本平面（BMP）的字符在 True 时写成代理对**（`encoder.py` 第 59–67 行，纯 Python 实现 `py_encode_basestring_ascii`）：

   ```python
   if n < 0x10000:
       return '\\u{0:04x}'.format(n)
   else:
       # surrogate pair
       n -= 0x10000
       s1 = 0xd800 | ((n >> 10) & 0x3ff)
       s2 = 0xdc00 | (n & 0x3ff)
       return '\\u{0:04x}\\u{1:04x}'.format(s1, s2)
   ```

   所以 😀（U+1F600）会变成 `\ud83d\ude00` 两段。文档正文没有专门讲这一点，这是源码和实测得出的。
   说明：平时实际跑的是 C 加速版（`_json` 模块里的 `encode_basestring_ascii`，见 `encoder.py` 第 5–16、71–72 行的导入和回退逻辑）。C 代码我没有逐行读，只通过下面的实测确认它的输出和纯 Python 版一致。

## 三、本机实测（Python 3.14.4，Linux/GCC 构建的 CPython）

注意本机是 3.14.4，文档读的是 3.15.2；本机的 `json/__init__.py` 和 `json/encoder.py` 里跟 `ensure_ascii` 有关的代码与上面 `main` 分支的一致。

| 做了什么 | 结果 |
| --- | --- |
| `inspect.signature(json.dump)` | `(obj, fp, *, skipkeys=False, ensure_ascii=True, ...)` |
| `json.dumps("中文é😀")` | `"\u4e2d\u6587\u00e9\ud83d\ude00"`（😀 变成 `\ud83d\ude00` 代理对） |
| `json.dumps("中文é😀", ensure_ascii=False)` | `"中文é😀"` |
| 两种输出分别 `json.loads` 后比较 | 相等（`True`） |
| `json.dumps('\x00\n"\\\x7f\u2028', ensure_ascii=False)` | `\u0000`、`\n`、`\"`、`\\` 被转义；U+007F 和 U+2028 原样输出 |
| 同上，`ensure_ascii=True` | U+007F 变 `\u007f`，U+2028 变 `\u2028` |
| 往 `encoding="ascii"` 的文本文件 `json.dump("中文", f, ensure_ascii=False)` | `UnicodeEncodeError: 'ascii' codec can't encode characters ...` |
| 往同样的 ascii 文件用默认值写 | 成功，内容为 `"\u4e2d\u6587"` |
| `json.dump("x", io.BytesIO())` | `TypeError: a bytes-like object is required, not 'str'` |
| 含落单代理项的字符串 `"\ud83d"`，`ensure_ascii=False` | 原样输出（之后若按 UTF-8 写文件会编码失败，这一步没有实测） |

## 四、实际使用上的结论

下面每条都标了依据是"文档明说""源码/实测"还是"推论"。

1. **想让 JSON 文件里直接看到中文，就用 `ensure_ascii=False`，并且打开文件时显式写 `encoding="utf-8"`。**
   - 文档明说：模块只产出 str、不管编码；RFC 推荐 UTF-8。
   - 实测：文件编码存不下这些字符时会抛 `UnicodeEncodeError`。
   - 推论：`open()` 不写 `encoding` 时用的是系统默认编码，不一定是 UTF-8，所以要显式指定。（`open()` 的默认编码规则属于 `open` 的文档，本次没有去核对。）

2. **默认值 True 的好处是"怎么存都不会坏"**：输出只有可打印 ASCII（文档明说），所以不管文件用什么 ASCII 兼容编码都能写进去（实测 ascii 编码成功）。代价是文件变大、人眼不好读。

3. **两种输出都是合法 JSON，数据等价。**
   - 文档明说：默认转义是 RFC "允许但不要求"的。
   - 实测：两种输出读回来相等。

4. **False 不等于"什么都不转义"**：引号、反斜杠、U+0000–U+001F 照样转义（文档明说，源码和实测一致）。

5. **False 时 U+2028/U+2029 会原样出现在输出里**（实测）。文档脚注说 JavaScript（ES 5.1）不接受字符串里直接出现这两个字符。如果要把 JSON 直接嵌进老的 JavaScript 代码里，这点要留意；这是把脚注和实测合起来的推论，文档没有把它和 `ensure_ascii` 直接挂钩。

6. **True 时非 BMP 字符（如 emoji）写成两个 `\uXXXX` 代理对**（源码和实测；文档正文没有专门写）。

## 五、不同版本文档的措辞差别

对比了 3.9 到 3.15 各版本的英文文档页面：

- **默认值没变过**：这些版本的签名里全是 `ensure_ascii=True`。
- **3.9–3.12 的旧说法**（标题分别为 3.9.25、3.10.22、3.11.18、3.12.16）：

  > If *ensure_ascii* is true (the default), the output is guaranteed to have all incoming non-ASCII characters escaped. If *ensure_ascii* is false, these characters will be output as-is.

  出处：<https://docs.python.org/3.9/library/json.html#json.dump>（3.10、3.11、3.12 页面里都没有 "non-printable" 这个词）

  "字符编码"一节的旧说法是 "...the resulting strings only contain ASCII characters."

- **3.13 起的新说法**（3.13.18、3.14.10、3.15.2）：改成了 "non-ASCII and non-printable characters"，并补上了 False 时仍要转义的字符清单；"字符编码"一节改成 "only contain printable ASCII characters"；参数说明也从大段文字改成了参数列表格式。
  出处：<https://docs.python.org/3.13/library/json.html#json.dump>

- 这是文档措辞变得更准确，还是行为也跟着变了，**本次没有查证**（没有去翻更新日志和提交记录，也没有在旧版本解释器上跑）。

## 六、没能核实的地方

- C 加速实现（`Modules/_json.c`）没有读源码，只靠实测确认输出和纯 Python 版一致。
- 3.13 文档措辞变化背后有没有行为变化，没有查。
- `open()` 默认编码的规则没有去查 `open` 的官方文档，上面只当作推论提了一句。
- 落单代理项在 `ensure_ascii=False` 下写入 UTF-8 文件会失败，这是推论，没有实测。
- 源码行号对应的是抓取当时的 `main` 分支；提交号是紧接着查到的最新提交，理论上两次请求之间可能有新提交，但行号已和本机 3.14.4 的文件核对过，一致。
- 实测只在本机 Python 3.14.4 上做，没有在 3.15 上跑。
