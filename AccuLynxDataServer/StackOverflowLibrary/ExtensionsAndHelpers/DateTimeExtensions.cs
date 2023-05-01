namespace StackOverflowLibrary.ExtensionsAndHelpers
{
    public static class DateTimeExtensions
    {
        public static long ToUnixTimestamp(this DateTime date)
        {
            return (long)(date.ToUniversalTime() - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
        }
    }
}
