\ Production mix problem with mixed variable types
Minimize
  cost: 3.14159 p1 + 2.71828 p2 + 1.5 p3 + 0.5 r1 + 0.75 r2
Subject To
  capacity: p1 + p2 + p3 + r1 <= 100
  demand_min: 2 p1 + 3 p2 + p3 >= 50
  balance: r1 + r2 - p1 - p2 = 10
Bounds
  0 <= p1 <= 40
  0 <= p2 <= 30
  0 <= p3 <= 50
  -10 <= r1 <= 60
  0 <= r2 <= 80
General
  p1 p2 p3
End
