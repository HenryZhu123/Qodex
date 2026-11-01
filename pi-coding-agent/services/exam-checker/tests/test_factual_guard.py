from exam_checker.parsing.factual_guard import check_factual_guards


def test_detects_address_capacity_contradiction() -> None:
    result = check_factual_guards(
        "若计算机主存地址为4 位，按字节编址，Cache 数据区大小为32KB，"
        "主存块大小为32B，采用直接映射方式。"
    )

    assert result is not None
    assert result.has_error is True
    assert "地址位宽" in result.reason


def test_detects_cpi_definition_contradiction() -> None:
    result = check_factual_guards("P的平均CPI为0.5，且每条指令平均需要2个时钟周期。")

    assert result is not None
    assert "CPI" in result.reason


def test_detects_modulation_capacity_contradiction() -> None:
    result = check_factual_guards("采用4个幅值的ASK调制（每个符号携带3个比特）。")

    assert result is not None
    assert "调制阶数" in result.reason


def test_detects_tcp_syn_sequence_number_contradiction() -> None:
    result = check_factual_guards("甲乙建立TCP连接，且SYN段不占用序列号。")

    assert result is not None
    assert "SYN" in result.reason


def test_detects_timeout_state_contradiction() -> None:
    result = check_factual_guards(
        "计时器发生了超时，且超时后拥塞窗口与慢开始门限均保持不变。"
    )

    assert result is not None
    assert "超时" in result.reason


def test_detects_invalid_heap_claim() -> None:
    result = check_factual_guards(
        "已知关键字序列28, 22, 20, 19, 8, 12, 15, 5是小根堆，对该堆删除。"
    )

    assert result is not None
    assert "小根堆" in result.reason


def test_allows_consistent_numeric_facts() -> None:
    result = check_factual_guards(
        "若计算机主存地址为32位，Cache数据区大小为32KB，主存块大小为32B。"
        "程序平均CPI为2，且每条指令平均需要2个时钟周期。"
        "采用4个幅值的ASK调制（每个符号携带2个比特）。"
    )

    assert result is None
