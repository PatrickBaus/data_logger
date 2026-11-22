# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/PatrickBaus/data_logger/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|------------------------------------ | -------: | -------: | -------: | -------: | ------: | --------: |
| \_version.py                        |        1 |        0 |        0 |        0 |    100% |           |
| data\_logger.py                     |      149 |       12 |       22 |        4 |     89% |108, 210, 213-215, 294, 300-309, 313, 317, 323 |
| devices/\_\_init\_\_.py             |        8 |        0 |        0 |        0 |    100% |           |
| devices/coherent.py                 |       44 |       26 |        0 |        0 |     41% |30, 33-35, 38-39, 44, 47, 50, 53, 56-62, 65, 68-73, 76-77 |
| devices/connections/\_\_init\_\_.py |        6 |        0 |        0 |        0 |    100% |           |
| devices/connections/base.py         |       76 |        3 |       14 |        3 |     93% |95-\>exit, 139, 160, 169 |
| devices/connections/ethernet.py     |       47 |        2 |        0 |        0 |     96% |     73-74 |
| devices/connections/gpib.py         |       29 |        0 |        0 |        0 |    100% |           |
| devices/connections/prologix.py     |       33 |        0 |        0 |        0 |    100% |           |
| devices/connections/serial.py       |       72 |        6 |       18 |        0 |     93% |138-139, 155-156, 161-162 |
| devices/e\_plus\_e.py               |       41 |       23 |        0 |        0 |     44% |28, 36, 39, 42, 45-51, 54, 57-62, 65-70, 73 |
| devices/errors.py                   |        1 |        0 |        0 |        0 |    100% |           |
| devices/fluke.py                    |      158 |       63 |       12 |        1 |     61% |68, 71, 80, 83, 86, 89, 92, 95, 98, 107, 132-135, 139-141, 144, 155-158, 170, 173-177, 187-191, 194, 197-199, 211, 214-218, 228, 231, 234, 237-242, 245, 248-252, 255-259, 262 |
| devices/ilx.py                      |       94 |       49 |        4 |        0 |     46% |37, 58, 64, 67-71, 74-78, 81-85, 91-98, 101-104, 107-112, 115, 118-122, 125, 128, 131, 134-138 |
| devices/keithley.py                 |      115 |       54 |        6 |        2 |     52% |32-37, 40, 43, 46, 61, 64, 67, 70-73, 86-93, 98, 104-107, 114-116, 126-127, 144, 147, 155-159, 162, 166, 169-176, 179, 182, 185, 188, 191, 205-208 |
| devices/keysight.py                 |      131 |       67 |        2 |        0 |     48% |35, 38-39, 42, 48, 51-55, 58-63, 66-71, 74-79, 82-87, 106-109, 112, 122-129, 132, 135, 150, 153, 156-164, 178-180, 188-192, 195, 198, 201, 207, 210 |
| endpoints/\_\_init\_\_.py           |        3 |        0 |        0 |        0 |    100% |           |
| endpoints/filewriter.py             |       66 |        5 |       14 |        3 |     90% |47-\>50, 74-\>exit, 77-78, 87, 111-112 |
| endpoints/mqtt.py                   |      113 |       17 |       28 |        3 |     80% |178-\>exit, 182, 196-\>199, 207-209, 211, 216-232, 235, 253-254 |
| errors.py                           |        4 |        0 |        0 |        0 |    100% |           |
| factories/\_\_init\_\_.py           |        3 |        0 |        0 |        0 |    100% |           |
| factories/device\_factory.py        |       16 |        0 |        0 |        0 |    100% |           |
| factories/endpoint\_factory.py      |        5 |        0 |        0 |        0 |    100% |           |
| factories/generic\_factory.py       |       17 |        3 |        0 |        0 |     82% | 40, 65-66 |
| logger/\_\_init\_\_.py              |        2 |        0 |        0 |        0 |    100% |           |
| logger/logger.py                    |      350 |      127 |       32 |        0 |     66% |225-227, 243, 298-300, 303, 306, 309-313, 316, 343-346, 369-371, 374-381, 406-409, 442-445, 448-452, 485-487, 490-497, 503-516, 565-566, 569-576, 585-592, 613-615, 630-633, 636-640, 646-649, 656, 659, 662, 665, 668, 671, 686-688, 692-701, 734-736, 740-742, 760, 776-779, 782-784, 795-803, 828-830, 833-835, 853, 858-860 |
| **TOTAL**                           | **1584** |  **457** |  **152** |   **16** | **71%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/PatrickBaus/data_logger/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/PatrickBaus/data_logger/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/PatrickBaus/data_logger/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/PatrickBaus/data_logger/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2FPatrickBaus%2Fdata_logger%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/PatrickBaus/data_logger/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.