use std::time::Duration;
use util_demo::utils::parse_duration;

#[test]
fn test_parse_duration_table() {
    struct TestCase {
        input: &'static str,
        expected: Option<Duration>,
    }

    let tests = vec![
        // Happy path
        TestCase {
            input: "10s",
            expected: Some(Duration::from_secs(10)),
        },
        TestCase {
            input: "2m",
            expected: Some(Duration::from_secs(2 * 60)),
        },
        TestCase {
            input: "1h",
            expected: Some(Duration::from_secs(1 * 3600)),
        },
        // Edge cases - zero
        TestCase {
            input: "0s",
            expected: Some(Duration::from_secs(0)),
        },
        TestCase {
            input: "0m",
            expected: Some(Duration::from_secs(0)),
        },
        TestCase {
            input: "0h",
            expected: Some(Duration::from_secs(0)),
        },
        // Edge cases - whitespace
        TestCase {
            input: "  5s  ",
            expected: Some(Duration::from_secs(5)),
        },
        TestCase {
            input: "\t3m\n",
            expected: Some(Duration::from_secs(3 * 60)),
        },
        // Edge cases - very large numbers
        TestCase {
            input: "18446744073709551615s",
            expected: Some(Duration::from_secs(18446744073709551615)),
        },
        // Error cases - empty string
        TestCase {
            input: "",
            expected: None,
        },
        TestCase {
            input: "   ",
            expected: None,
        },
        // Error cases - unknown unit
        TestCase {
            input: "5d",
            expected: None,
        },
        TestCase {
            input: "10ms",
            expected: None,
        },
        // Error cases - negative values
        TestCase {
            input: "-5s",
            expected: None,
        },
        TestCase {
            input: "-10m",
            expected: None,
        },
        // Error cases - non-numeric prefix
        TestCase {
            input: "abc123s",
            expected: None,
        },
        TestCase {
            input: "s",
            expected: None,
        },
        TestCase {
            input: "m",
            expected: None,
        },
        TestCase {
            input: "h",
            expected: None,
        },
    ];

    for (i, test) in tests.iter().enumerate() {
        let result = parse_duration(test.input);
        assert_eq!(
            result, test.expected,
            "Test case {} failed: input={:?}",
            i, test.input
        );
    }
}
