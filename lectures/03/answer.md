# 第3回 解答

## 演習

- 第1回（素のLLM）とエージェントの回答の違い：
- `--trace` で見えたツール呼び出し（ツール名と引数）：
- 1つの質問での LLM 呼び出し回数（`requests`）：
- 追加したツールと、docstring に書いた説明：

## 宿題

- 取り組んだレベル：基礎 / 実装 / 発展
- やったこと：
- 結果：
- 気づき・疑問：

# 第3回 解答

## 演習

- 第1回（素のLLM）とエージェントの回答の違い：
  - 質問：「AIE2026の講座の宿題にある「3レベル」とは何ですか？」
  - 第1回 `app.ask`：講座の中身を知らないため、「初級・中級・上級」「プロンプトの思考レベル」「難易度別の課題」という一般論の解釈を3つ並べ、「受講生コミュニティで質問する」よう勧めた。用語集の定義（基礎・実装・発展）とは違う
  - 第3回 `app.agent`：`search_glossary({'query': '3レベル'})` で用語集を引いてから、「基礎（講義内容の確認）・実装（自分でコードを書く）・発展（調査や試行）」「どれか1つで完了」「原則採点しない」と、用語集の定義どおりに答えた。最後に「関連する回：第1回」と示した（requests=2, tool_calls=1）
  - 同じモデル（gemini-3.5-flash-lite）でも、講座に固有のことは、手元のデータを検索させないと正しく答えられない
- `--trace` で見えたツール呼び出し（ツール名と引数）：「LoRAとQLoRAの違いは？」で、用語を1つずつ2回検索した

  ```text
  [tool call]   search_glossary({'query': 'LoRA'})
  [tool call]   search_glossary({'query': 'QLoRA'})
  ```

- 1つの質問での LLM 呼び出し回数（`requests`）：2（tool_calls=2）。1回目で2つの検索をまとめて頼み、2回目で検索結果を見て回答を書いた

  ```text
  [usage] RunUsage(cost=Decimal('0.0008463'), details={'text_prompt_tokens': 1196}, input_text_tokens=1196, input_tokens=1196, output_tokens=195, requests=2, tool_calls=2)
  ```

- 追加したツールと、docstring に書いた説明：`make_quiz(lecture: int)`。docstring には「指定した回の用語から確認問題を1問作り、問題と答えを返す。『第2回の確認問題を出して』のように復習用の問題を求められたときに使う。answer は採点用なので利用者が答えるまで見せない」と書いた。用語集に無い回（第0回など）は、問題を作れる回の一覧を返す
  - `--list-tools` に `make_quiz` と docstring が出た（ツールは3個）
  - 「第2回の内容から確認問題を1問出して」で `make_quiz({'lecture': 2})` が呼ばれ、「「過学習」の意味は？」と問題だけを出し、答えは「あなたの回答を教えてください。その後に正解をお伝えします」と伏せた（requests=2, tool_calls=1）
  - `uv run pytest -q`：15 passed

## 宿題

- 取り組んだレベル：実装
- やったこと：
  - `app/tools.py` に `save_learning_log(title, content)` を追加した。保存先は `learning_log/YYYY-MM-DD.md`（日本時間の日付）で、`## HH:MM 見出し` の形で追記する
    - ファイル名は日付だけで決め、モデルが作る文字列（title）をパスに使わない。`../` などで `learning_log/` の外に書かれないようにするため
    - 追記（上書きしない）。空の入力や長すぎる入力（title 60字・content 2000字超）は保存せずに理由を返す
  - `app/agent.py` で `agent.tool_plain(tools.save_learning_log, requires_approval=True)` と登録し、`output_type=[str, DeferredToolRequests]` を加えた
  - CLI に `ask_approvals` と `run_with_approval` を追加した。承認待ちで止まったら、呼び出しの引数（title・content）を表示して `[y/N]` を聞き、結果（`DeferredToolResults`）と `message_history=result.all_messages()` を渡して `run_sync` をもう一度実行する。y 以外は `ToolDenied` で断り、断った旨がモデルに伝わる
  - `INSTRUCTIONS` に「学習の記録を残すよう頼まれたら save_learning_log を使う。頼まれていないときは保存しない」を加えた
  - API キーを使わないテスト `tests/test_learning_log.py`（9件）を追加した
- 結果：
  - `uv run python -m app.agent --list-tools`：ツールが4個になり、`save_learning_log` と docstring、引数（title・content）が出た
  - `uv run pytest -q`：24 passed（演習時の15件＋追加した9件）
  - 承認して保存した例（`--trace "LoRAとQLoRAの違いを調べて、学習ログに保存して"` で y と答えた）：

    ```text
    [承認待ち] save_learning_log
      content: - **LoRA**: 事前学習済みモデルの重みを固定し、低ランク行列（2つの小さな行列の積）の更新分のみを学習してパラメータ数やメモリを削減するPEFT手法。
        - **QLoRA**: ベースモデルの重みを4ビット等に量子化してさらにメモリを大幅に節約した上で、LoRAを用いて学習する手法。より大きなモデルを限られたGPU環境で扱えるようにする。
      title: LoRAとQLoRAの違い
    この内容で実行しますか？ [y/N]: y
    （回答の本文は省略）
    ご要望の通り、上記のまとめを学習ログ（`learning_log/2026-11-08.md`）に保存しました。

    関係する回：第2回

    --- trace ---
    [tool call]   search_glossary({'query': 'LoRA'})
    [tool call]   search_glossary({'query': 'QLoRA'})
    [tool return] search_glossary -> [{"term": "LoRA", "lecture": 2, ...
    [tool return] search_glossary -> [{"term": "QLoRA", "lecture": 2, ...
    [tool call]   save_learning_log({'content': '- **LoRA**: ...', 'title': 'LoRAとQLoRAの違い'})
    [tool return] save_learning_log -> learning_log/2026-11-08.md に「LoRAとQLoRAの違い」を保存しました。…
    [usage] RunUsage(cost=Decimal('0.0018876'), details={'text_prompt_tokens': 3292}, input_text_tokens=3292, input_tokens=3292, output_tokens=360, requests=3, tool_calls=3)
    ```

  - 断った例（同じ質問で N と答えた）：

    ```text
    [承認待ち] save_learning_log
      content: - LoRA: 事前学習済みの重みを固定し、重みの更新分（低ランク行列）のみを学習するPEFT手法。少ないパラメータと小さなファイルサイズで学習・保存が可能。
        - QLoRA: ベースモデルの重みを4ビット等に量子化してメモリを大幅に節約しつつ、LoRAを適用して学習する手法。より大きなモデルを小さなGPU環境で扱える。
      title: LoRAとQLoRAの違い
    この内容で実行しますか？ [y/N]: N
    （回答の本文は省略）
    「学習ログに保存して」とのご依頼でしたが、保存を実行するにはあなたの承認（許可）が必要です。学習ログに保存しますか？ よろしければ「はい」とお知らせください。

    --- trace ---
    [tool call]   search_glossary({'query': 'LoRA'})
    [tool call]   search_glossary({'query': 'QLoRA'})
    [tool return] search_glossary -> [{"term": "LoRA", "lecture": 2, ...
    [tool return] search_glossary -> [{"term": "QLoRA", "lecture": 2, ...
    [tool call]   save_learning_log({'content': '- LoRA: ...', 'title': 'LoRAとQLoRAの違い'})
    [tool return] save_learning_log -> 利用者が実行を断りました。実行していないことを利用者に伝えてください。…
    [usage] RunUsage(cost=Decimal('0.0019169'), details={'text_prompt_tokens': 3273}, input_text_tokens=3273, input_tokens=3273, output_tokens=374, requests=3, tool_calls=2)
    ```

  - 保存を頼まない質問（`--trace "LoRAとは？"`）で save_learning_log が呼ばれたか：呼ばれなかった。`[承認待ち]` も出ず、ツール呼び出しは `search_glossary({'query': 'LoRA'})` の1回だけだった（requests=2, tool_calls=1）
  - 保存されたファイル（`learning_log/` は .gitignore 済みで commit されない）。y と答えた1件だけがあり、N と答えた回の分は無い：

    ```markdown
    ## 01:09 LoRAとQLoRAの違い

    - **LoRA**: 事前学習済みモデルの重みを固定し、低ランク行列（2つの小さな行列の積）の更新分のみを学習してパラメータ数やメモリを削減するPEFT手法。
    - **QLoRA**: ベースモデルの重みを4ビット等に量子化してさらにメモリを大幅に節約した上で、LoRAを用いて学習する手法。より大きなモデルを限られたGPU環境で扱えるようにする。
    ```

  - `requests` の比較：

    | 実行 | save_learning_log | requests | tool_calls | input_tokens |
    |---|---|---|---|---|
    | 演習「LoRAとQLoRAの違いは？」 | 呼ばれない | 2 | 2 | 1,196 |
    | 「LoRAとは？」 | 呼ばれない | 2 | 1 | 1,623 |
    | 保存を頼む（1回目） | 呼ばれない | 2 | 2 | 1,894 |
    | 保存を頼む → N | 呼ばれた → 断った | 3 | 2 | 3,273 |
    | 保存を頼む → y | 呼ばれた → 実行 | 3 | 3 | 3,292 |

    - 保存のツールが呼ばれると requests が1回増えた。①検索を2つ頼む → ②save_learning_log を頼む（ここで承認待ちで止まる）→ ③承認の結果を見て回答を書く、の3回
    - 断った呼び出しは tool_calls に数えられない（N は2、y は3）
    - 保存のツールが呼ばれた回は input_tokens が約2倍になった。モデルは前の会話を覚えていないので、続きの実行ではそれまでの会話を全部送り直しているため
    - 演習の行は承認の仕組みを入れる前（ツール2個）の実行なので、input_tokens はそのまま比べられない
  - 公式ドキュメントと実行で確かめたこと：
    - `output_type` に `DeferredToolRequests` を入れないと、ツールの登録はできるが、モデルが承認付きのツールを呼んだ時点で `UserError` になる（`test_without_deferred_output_type_fails_when_called`）
    - 承認を待っている間、ツールの本体は実行されない（`test_run_stops_before_saving`）。実際に N と答えた回は `learning_log/` に書かれていない
    - 続きの実行に `message_history` を渡さないと `UserError`（履歴が空）になる。モデルは前の会話を覚えていないので、ハーネスが全部渡し直す
    - 続きの実行は別の run なので、`usage` を渡さないと `requests` が2回目の分だけになる。渡して合計にした（`test_usage_counts_both_runs`）。実行でも requests=3（承認の前に2回＋後に1回）と出た。この点は公式ドキュメントの Deferred Tools の節には書かれておらず、講座と同じ版（2.57.0）で実行して確かめた
- 気づき・疑問（想定と違った点と、考えたこと）：
  - 想定：「学習ログに保存して」と頼めば、毎回 save_learning_log が呼ばれて `[承認待ち]` が出る
    実際：1回目はツールが呼ばれず、モデルが回答の最後に文章で「この内容を学習の記録として保存しますか？」と聞き返して終わった（requests=2、tool_calls は検索の2回だけ）。2回目・3回目は同じ質問で呼ばれた
    考えたこと：
    - docstring の「保存の前に、利用者の承認を求める」を、モデルが「呼ぶ前に自分で確認せよ」という指示と受け取った可能性がある。実際、回答の最後で文章で確認していた
    - docstring は人向けの説明ではなく、モデルへの指示（プロンプト）の一部。承認はプログラムが行うので、「呼ぶ前に文章で確認しない」と書くべきだった
    - 同じ質問でも3回中1回だけ動きが違った。1回の実行で「動いた／動かない」と判断するのは危ない
  - 想定：N と答えたら、モデルは「保存していない」と伝えて終わる
    実際：保存していないことは伝えたが、続けて「学習ログに保存しますか？ よろしければ『はい』とお知らせください」と返した。この CLI は1回の質問で終わるので、「はい」と返す先がない
    考えたこと：
    - モデルは CLI が1回で終わる作りだと知らず、ToolDenied の文（「実行していないことを伝えて」）しか見ていない。「もう一度勧めない」とは書いていないので、会話が続く前提で聞き返したと考えられる
    - はっきり断ったのにもう一度勧めるのは、Human-in-the-loop として良くない。ToolDenied の文に「再度の保存は勧めない」と書き足すか、会話を続けられる CLI にする（第1回の宿題「実装」とつながる）
    - モデルに渡す文は、ツールの結果も含めて、すべてプロンプトとして書く必要がある
  - 疑問：
    - 毎回 y を押すだけだと承認が形だけにならないか。短い記録は自動で保存し、長いものだけ聞くなど、条件付きの承認（`ApprovalRequired`）はどう線を引くのがよいか
    - 「保存するかどうか」の判断を、モデル（docstring・INSTRUCTIONS）とプログラムのどちらに持たせるべきか。実際には、今回は3回中1回呼ばれなかった
    - 会話を続けられる CLI で「はい」と返したら、モデルが再び save_learning_log を呼び、承認をもう一度聞くことになるのか。
