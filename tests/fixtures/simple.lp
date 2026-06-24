\ Simple LP test file
Minimize
  obj: x1 + 2 x2 + 3 x3
Subject To
  c1: 2 x1 + x2 + x3 <= 10
  c2: x1 + 3 x2 + x3 <= 8
Bounds
  0 <= x1 <= 5
  0 <= x2 <= 5
  0 <= x3 <= 5
End
