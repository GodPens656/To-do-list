import flet as ft

def main(page: ft.Page):
    page.add(
        ft.ExpansionTile(
            title=ft.Text("Недавнее"),
            #initially_expanded=True,
            controls=[
                ft.ListTile(title=ft.Text("Выпадающие списки в Flet")),
                ft.ListTile(title=ft.Text("Интерфейс для редактора узлов")),
                ft.ListTile(title=ft.Text("Измерение времени Python")),
                ft.ListTile(title=ft.Text("Проверка интернета на Python")),
            ],
        )
    )

ft.app(main)