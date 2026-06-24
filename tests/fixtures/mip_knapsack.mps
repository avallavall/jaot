NAME          knapsack
ROWS
 N  obj
 L  capacity
COLUMNS
    INT1      'MARKER'                 'INTORG'
    x1  obj  -8.0  capacity  2.0
    x2  obj  -11.0  capacity  3.0
    x3  obj  -6.0  capacity  1.0
    x4  obj  -4.0  capacity  2.0
    x5  obj  -7.0  capacity  3.0
    INT1END   'MARKER'                 'INTEND'
RHS
    rhs  capacity  7.0
BOUNDS
 BV  bnd  x1
 BV  bnd  x2
 BV  bnd  x3
 BV  bnd  x4
 BV  bnd  x5
ENDATA
