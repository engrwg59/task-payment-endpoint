-- The test suite drops and rebuilds its schema on every run, so it needs a
-- database of its own, separate from the one the application uses.
CREATE DATABASE payments_test OWNER payments;
