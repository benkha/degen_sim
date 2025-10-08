from IPython.display import HTML, Markdown, display


def hide_raw_cells(default: bool = True):
    return HTML(
        f"""
        <script src="https://ajax.googleapis.com/ajax/libs/jquery/3.5.1/jquery.min.js"></script>
        <script>
            code_show={"true" if default else "false"}
            function code_toggle() {{
                code_show ? $('div.input').hide() : $('div.input').show();
                code_show ? $('div.jp-InputArea').hide() : $('div.jp-InputArea').show();
                code_show = !code_show;
            }}
            $(document).ready(code_toggle);
        </script>
        <form action="javascript:code_toggle()">
            <input type="submit" value="Toggle Notebook Code">
        </form>
    """
    )


def markdown(text: str):
    return display(Markdown(text))
